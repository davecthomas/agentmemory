---
timestamp: "2026-04-04T23:24:40Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_3fda4373b0"
decision_candidate: false
ai_generated: true
ai_model: "claude-unknown"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/install.py"
verification:
  - "git diff:  1 file changed, 42 insertions(+); def read_version(repo_root: Path) -> str:; \"\"\"Read the version string from pyproject.toml.; Args:"
---

## Why

- Looks good. To answer your version question: `pyproject.toml` is the single source of truth. `install.py` reads it at runtime — no duplication. The README doesn't currently show a version, and I'd recommend keeping it that way (one fewer thing to sync). If you ever want it there, it should be generated from `pyproject.toml` too, not manually maintained.

## Repo changes

- Updated scripts/shared-repo-memory/install.py

## Evidence

- git diff:  1 file changed, 42 insertions(+); def read_version(repo_root: Path) -> str:; """Read the version string from pyproject.toml.; Args:

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
