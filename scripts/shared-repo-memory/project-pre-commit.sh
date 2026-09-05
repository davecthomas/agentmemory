#!/usr/bin/env bash
# project-pre-commit.sh -- Project-specific pre-commit checks for this repo.
#
# Generated shared-memory hooks call this script after the shared-memory
# publication guard passes. Repositories that do not need extra checks can omit
# this file entirely; the generated hook will skip delegation when it is absent.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

# black runs in --check mode alongside ruff. AGENTS.md requires both to be clean
# before any change is complete. This hook is the only place that enforces it,
# since the repo has no CI: unformatted code landed across several PRs while
# black was documented but unchecked.
if command -v poetry &>/dev/null; then
  poetry run black --check .
  poetry run ruff check scripts/ evals/
  poetry run pytest scripts/shared-repo-memory/test/ -q
  poetry run python evals/check_memory.py
elif [ -x "$repo_root/.venv/bin/ruff" ]; then
  "$repo_root/.venv/bin/black" --check .
  "$repo_root/.venv/bin/ruff" check scripts/ evals/
  "$repo_root/.venv/bin/python" -m pytest scripts/shared-repo-memory/test/ -q
  "$repo_root/.venv/bin/python" evals/check_memory.py
else
  black --check .
  ruff check scripts/ evals/
  pytest scripts/shared-repo-memory/test/ -q
  python3 evals/check_memory.py
fi
