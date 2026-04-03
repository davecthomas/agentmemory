---
timestamp: "2026-04-03T20:13:13Z"
author: "davidcthomas"
branch: "main"
thread_id: "8c48dbbd-7854-40a2-932e-f30d517db42b"
turn_id: "turn_956ccfd565"
decision_candidate: true
ai_generated: true
ai_model: "gpt-5.4"
ai_tool: "codex"
ai_surface: "codex-cli"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/prompt-guard.py"
verification:
  - "7. Improve error handling in shell scripts"
  - "Old code: `.replace(\"-\", \":\")` on full filename prefix converted ALL dashes to colons (4+ colons), then `count(\":\") == 2` always failed"
  - "**Fix 3: pyproject.toml** - Added `[tool.black]`, `[tool.ruff]`, `[tool.ruff.lint]` sections with `ignore = [\"E501\"]` (docstring lines)"
  - "echo \"[shared-repo-memory] warning: post-checkout memory catch-up failed (non-fatal)\" >&2"
  - "**Fix 7: Shell error handling** - Covered by fix 4 (git hooks); install.sh already used `set -euo pipefail`"
  - "Fix 7 pre-identified bugs: timestamp idempotency in post-turn-notify.py, README Python version, pyproject.toml tool configs, git hook silent failures, skills installation gap, variable naming, shell error handling"
  - "Replaced `|| true` with `if ! ...; then echo \"warning...\" >&2; fi`"
  - "Added `[tool.black]`, `[tool.ruff]`, `[tool.ruff.lint]` sections"
  - "**Ruff E501 false positives**: Long docstring lines aren't reformatted by black. Fixed by adding `ignore = [\"E501\"]` to `[tool.ruff.lint]`."
  - "**`prompt-guard.py` relies on payload `cwd`**: Claude Code may not populate `cwd` in UserPromptSubmit payload, causing silent no-op. Traced via: manual test worked; no trace entry in hook log for ai_api_unified session; session not marked in state file. Fix: use `Path.cwd()` (process cwd, which Claude Code sets to project dir) as primary, payload `cwd` as fallback."
  - "**`prompt-guard.py` silent failure**: Root cause identified as reliance on payload `cwd` field. Fix applied but not yet synced/committed."
  - "\"you had an API Error 500 so I don't know if you completed work. [listed 7 fix items]\""
  - "Verify by testing: `echo '{\"session_id\":\"test-xyz\",\"hook_event_name\":\"UserPromptSubmit\",\"cwd\":\"\"}' | python3 ~/.agent/shared-repo-memory/prompt-guard.py` from inside the ai_api_unified directory"
---

## Why

- <analysis>

## Repo changes

- Updated scripts/shared-repo-memory/prompt-guard.py

## Evidence

- 7. Improve error handling in shell scripts
- Old code: `.replace("-", ":")` on full filename prefix converted ALL dashes to colons (4+ colons), then `count(":") == 2` always failed
- **Fix 3: pyproject.toml** - Added `[tool.black]`, `[tool.ruff]`, `[tool.ruff.lint]` sections with `ignore = ["E501"]` (docstring lines)
- echo "[shared-repo-memory] warning: post-checkout memory catch-up failed (non-fatal)" >&2
- **Fix 7: Shell error handling** - Covered by fix 4 (git hooks); install.sh already used `set -euo pipefail`
- Fix 7 pre-identified bugs: timestamp idempotency in post-turn-notify.py, README Python version, pyproject.toml tool configs, git hook silent failures, skills installation gap, variable naming, shell error handling
- Replaced `|| true` with `if ! ...; then echo "warning..." >&2; fi`
- Added `[tool.black]`, `[tool.ruff]`, `[tool.ruff.lint]` sections
- **Ruff E501 false positives**: Long docstring lines aren't reformatted by black. Fixed by adding `ignore = ["E501"]` to `[tool.ruff.lint]`.
- **`prompt-guard.py` relies on payload `cwd`**: Claude Code may not populate `cwd` in UserPromptSubmit payload, causing silent no-op. Traced via: manual test worked; no trace entry in hook log for ai_api_unified session; session not marked in state file. Fix: use `Path.cwd()` (process cwd, which Claude Code sets to project dir) as primary, payload `cwd` as fallback.
- **`prompt-guard.py` silent failure**: Root cause identified as reliance on payload `cwd` field. Fix applied but not yet synced/committed.
- "you had an API Error 500 so I don't know if you completed work. [listed 7 fix items]"
- Verify by testing: `echo '{"session_id":"test-xyz","hook_event_name":"UserPromptSubmit","cwd":""}' | python3 ~/.agent/shared-repo-memory/prompt-guard.py` from inside the ai_api_unified directory

## Next

- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready.
