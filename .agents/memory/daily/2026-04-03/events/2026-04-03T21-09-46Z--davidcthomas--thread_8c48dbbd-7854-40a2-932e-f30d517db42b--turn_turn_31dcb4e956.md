---
timestamp: "2026-04-03T21:09:46Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_31dcb4e956"
decision_candidate: false
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/install.py"
  - "scripts/shared-repo-memory/prompt-guard.py"
  - "scripts/shared-repo-memory/session-start.py"
  - "skills/memory-bootstrap/SKILL.md"
  - "skills/news/SKILL.md"
verification:
  - "Tracked repo changes were detected in the working tree."
---

## Why

- There it is: `"reason": "no_api_key"`. **`ANTHROPIC_API_KEY` is not in the environment that Claude Code passes to hook subprocesses.** The auto-bootstrap spawns but exits immediately every time.

## Repo changes

- Updated scripts/shared-repo-memory/install.py
- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py
- Updated skills/memory-bootstrap/SKILL.md
- Updated skills/news/SKILL.md

## Evidence

- Tracked repo changes were detected in the working tree.

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
