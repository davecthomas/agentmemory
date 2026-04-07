#!/usr/bin/env bash
# project-pre-commit.sh -- Project-specific pre-commit checks for this repo.
#
# Generated shared-memory hooks call this script after the shared-memory
# publication guard passes. Repositories that do not need extra checks can omit
# this file entirely; the generated hook will skip delegation when it is absent.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

if command -v poetry &>/dev/null; then
  poetry run ruff check scripts/ skills/
  poetry run pytest scripts/shared-repo-memory/test/ -q
elif [ -x "$repo_root/.venv/bin/ruff" ]; then
  "$repo_root/.venv/bin/ruff" check scripts/ skills/
  "$repo_root/.venv/bin/python" -m pytest scripts/shared-repo-memory/test/ -q
else
  ruff check scripts/ skills/
  pytest scripts/shared-repo-memory/test/ -q
fi
