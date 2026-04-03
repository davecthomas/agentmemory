---
timestamp: "2026-04-03T20:36:45Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_043befa22c"
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
  - "Tracked repo changes were detected in the working tree."
---

## Why

- Done. Both hooks now say `memory-bootstrap` directly. Open a fresh session in instapic — the agent will be told to invoke `/memory-bootstrap` before anything else.

## Repo changes

- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py
- Updated skills/memory-bootstrap/SKILL.md
- Updated skills/news/SKILL.md

## Evidence

- Tracked repo changes were detected in the working tree.

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
