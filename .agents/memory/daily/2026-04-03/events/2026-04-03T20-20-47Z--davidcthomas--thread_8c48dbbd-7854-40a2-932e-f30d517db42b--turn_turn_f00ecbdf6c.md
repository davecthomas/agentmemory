---
timestamp: "2026-04-03T20:20:47Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_f00ecbdf6c"
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
verification:
  - "To test: clear the session state for instapic so prompt-guard fires again, then open a fresh session there:"
---

## Why

- Now the agent will receive an explicit instruction ("you MUST invoke the `news` skill now, before responding") rather than a polite suggestion ("offer to run"). 

## Repo changes

- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/session-start.py

## Evidence

- To test: clear the session state for instapic so prompt-guard fires again, then open a fresh session there:

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
