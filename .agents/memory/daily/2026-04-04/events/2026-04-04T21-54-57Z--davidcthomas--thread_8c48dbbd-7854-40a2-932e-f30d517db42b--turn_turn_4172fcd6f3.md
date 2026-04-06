---
timestamp: "2026-04-04T21:54:57Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_4172fcd6f3"
decision_candidate: true
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "docs/shared-repo-memory-system-design.md"
  - "scripts/shared-repo-memory/auto-bootstrap.py"
  - "scripts/shared-repo-memory/build-catchup.py"
  - "scripts/shared-repo-memory/common.py"
  - "scripts/shared-repo-memory/post-compact.py"
  - "scripts/shared-repo-memory/post-turn-notify.py"
  - "scripts/shared-repo-memory/promote-adr.py"
  - "scripts/shared-repo-memory/prompt-guard.py"
  - "scripts/shared-repo-memory/rebuild-summary.py"
  - "scripts/shared-repo-memory/session-start.py"
verification:
  - "git diff:  10 files changed, 97 insertions(+), 22 deletions(-); ai-generated: true; ai-model: <model from source shard>; ai-tool: <tool from source shard>"
---

## Why

- Align the shared-memory bootstrap, summary, and prompt recovery flow with the intended repo-wide behavior.

## Repo changes

- Updated docs/shared-repo-memory-system-design.md
- Updated scripts/shared-repo-memory/auto-bootstrap.py
- Updated scripts/shared-repo-memory/build-catchup.py
- Updated scripts/shared-repo-memory/common.py
- Updated scripts/shared-repo-memory/post-compact.py
- Updated scripts/shared-repo-memory/post-turn-notify.py
- Updated scripts/shared-repo-memory/promote-adr.py
- Updated scripts/shared-repo-memory/prompt-guard.py
- Updated scripts/shared-repo-memory/rebuild-summary.py
- Updated scripts/shared-repo-memory/session-start.py

## Evidence

- git diff:  10 files changed, 97 insertions(+), 22 deletions(-); ai-generated: true; ai-model: <model from source shard>; ai-tool: <tool from source shard>

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
