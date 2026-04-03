---
timestamp: "2026-04-03T21:26:49Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_9e71dd4fe7"
decision_candidate: true
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/install.py"
  - "scripts/shared-repo-memory/post-turn-notify.py"
  - "scripts/shared-repo-memory/prompt-guard.py"
  - "scripts/shared-repo-memory/session-start.py"
  - "skills/memory-bootstrap/SKILL.md"
  - "skills/news/SKILL.md"
verification:
  - "git diff:  6 files changed, 246 insertions(+), 34 deletions(-); \"auto-bootstrap.py\",; import subprocess; # ---------------------------------------------------------------------------"
---

## Why

- The key change: the Workflow now opens with a mandatory `find` command the agent must actually run. It can't reason past it — it either finds shard files or it doesn't. Previously the agent was reasoning from ADR count without touching the filesystem.

## Repo changes

- Updated scripts/shared-repo-memory/install.py
- Updated scripts/shared-repo-memory/post-turn-notify.py
- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py
- Updated skills/memory-bootstrap/SKILL.md
- Updated skills/news/SKILL.md

## Evidence

- git diff:  6 files changed, 246 insertions(+), 34 deletions(-); "auto-bootstrap.py",; import subprocess; # ---------------------------------------------------------------------------

## Next

- The key change: the Workflow now opens with a mandatory `find` command the agent must actually run. It can't reason past it — it either finds shard files or it doesn't. Previously the agent was reasoning from ADR count without touching the filesystem.
