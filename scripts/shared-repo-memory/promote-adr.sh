#!/usr/bin/env bash
# promote-adr.sh -- Convenience wrapper for ADR promotion.
#
# Resolves the git repo root automatically and delegates to promote-adr.py.
# Callers pass the path to a decision-candidate event shard as the first
# positional argument, plus any additional flags understood by promote-adr.py
# (e.g., --title "My ADR title").
#
# Usage:
#   promote-adr.sh <shard-path> [--title <title>]
#
# Example:
#   ./scripts/shared-repo-memory/promote-adr.sh \
#       .agents/memory/daily/2026-04-03/events/2026-04-03T12-00-00Z--alice--thread_abc--turn_xyz.md \
#       --title "Use immutable event shards for memory capture"
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

# exec replaces this shell with the Python script, forwarding all arguments
# so the caller's shard path and --title flag are passed through unchanged.
exec "$HOME/.agent/shared-repo-memory/promote-adr.py" --repo-root "$repo_root" "$@"
