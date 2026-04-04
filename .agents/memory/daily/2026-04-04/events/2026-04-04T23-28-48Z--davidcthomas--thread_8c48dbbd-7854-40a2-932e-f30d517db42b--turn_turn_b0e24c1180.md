---
timestamp: "2026-04-04T23:28:48Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_b0e24c1180"
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
  - "git diff:  1 file changed, 47 insertions(+); def read_version(repo_root: Path) -> str:; \"\"\"Read the version string from pyproject.toml.; Args:"
---

## Why

- That's the script/cursive style with only basic ASCII characters — no backticks or unicode that terminals mangle. How's that look?

## Repo changes

- Updated scripts/shared-repo-memory/install.py

## Evidence

- git diff:  1 file changed, 47 insertions(+); def read_version(repo_root: Path) -> str:; """Read the version string from pyproject.toml.; Args:

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
