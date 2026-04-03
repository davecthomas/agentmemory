---
timestamp: "2026-04-03T20:46:17Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_50d176c75d"
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
  - "Claude Code stores the API key securely (macOS keychain) and injects it as `ANTHROPIC_API_KEY` into hook subprocess environments. The manual terminal test fails because the key isn't in the shell env \u2014 but when session-start spawns `auto-bootstrap.py`, it inherits Claude Code's env and the key will be present."
  - "To test manually, you can run:"
---

## Why

- Claude Code stores the API key securely (macOS keychain) and injects it as `ANTHROPIC_API_KEY` into hook subprocess environments. The manual terminal test fails because the key isn't in the shell env — but when session-start spawns `auto-bootstrap.py`, it inherits Claude Code's env and the key will be present.

## Repo changes

- Updated scripts/shared-repo-memory/install.py
- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py
- Updated skills/memory-bootstrap/SKILL.md
- Updated skills/news/SKILL.md

## Evidence

- Claude Code stores the API key securely (macOS keychain) and injects it as `ANTHROPIC_API_KEY` into hook subprocess environments. The manual terminal test fails because the key isn't in the shell env — but when session-start spawns `auto-bootstrap.py`, it inherits Claude Code's env and the key will be present.
- To test manually, you can run:

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
