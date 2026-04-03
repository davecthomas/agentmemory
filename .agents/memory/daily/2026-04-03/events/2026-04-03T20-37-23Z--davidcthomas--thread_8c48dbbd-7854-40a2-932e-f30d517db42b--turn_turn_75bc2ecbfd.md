---
timestamp: "2026-04-03T20:37:23Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_75bc2ecbfd"
decision_candidate: false
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/prompt-guard.py"
  - "scripts/shared-repo-memory/session-start.py"
  - "skills/memory-bootstrap/SKILL.md"
  - "skills/news/SKILL.md"
verification:
  - "Want me to build that? It would:"
---

## Why

- You're right, it should be simple. The reason it's not: `SessionStart` can run Python scripts directly (it already calls `bootstrap-repo.py`), but `memory-bootstrap` is an AI skill — it needs the LLM to analyze commits and docs. Hooks can't invoke the LLM.

## Repo changes

- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py
- Updated skills/memory-bootstrap/SKILL.md
- Updated skills/news/SKILL.md

## Evidence

- Want me to build that? It would:

## Next

- You're right, it should be simple. The reason it's not: `SessionStart` can run Python scripts directly (it already calls `bootstrap-repo.py`), but `memory-bootstrap` is an AI skill — it needs the LLM to analyze commits and docs. Hooks can't invoke the LLM.
