#!/usr/bin/env bash
# run-catchup.sh -- Rebuild the local catch-up digest after a git operation.
#
# Called by the git hooks in .githooks/ (post-checkout, post-merge,
# post-rewrite) so that .codex/local/catchup.md is always current after any
# operation that changes the working tree.
#
# The first argument ($1) is an optional trigger label that appears in
# sync_state.json for diagnostics.  The .githooks/ scripts pass the hook name
# (e.g., "post-checkout", "post-merge") so the sync state records what
# initiated each rebuild.
#
# Usage:
#   run-catchup.sh [trigger]
#   run-catchup.sh post-checkout
set -euo pipefail

# Capture the trigger label before shifting arguments.
trigger="${1:-manual}"
shift || true

repo_root="$(git rev-parse --show-toplevel)"

# exec replaces this shell with the Python script, passing the resolved repo
# root and trigger label as arguments.
exec "$HOME/.agent/shared-repo-memory/build-catchup.py" --repo-root "$repo_root" --trigger "$trigger"
