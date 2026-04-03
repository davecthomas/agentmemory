#!/usr/bin/env bash
# notify-wrapper.sh -- Thin wrapper to invoke post-turn-notify.py for Codex.
#
# Codex does not fire a Stop hook the way Claude Code does.  Instead, the Codex
# post-turn integration pipes the hook payload into this wrapper script.
#
# This script resolves the repo root (so post-turn-notify.py operates on the
# correct repo when the caller's cwd is a subdirectory) and delegates immediately
# to the installed Python script via exec, replacing this process rather than
# spawning a child.
#
# Reads the hook payload JSON from stdin and passes it through to post-turn-notify.py.
#
# Usage (typically invoked by the Codex notify integration):
#   <payload_json> | ./scripts/shared-repo-memory/notify-wrapper.sh
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"

# exec replaces the shell process with the Python script, preserving stdin
# so the caller's pipe delivers the payload correctly.
exec "$HOME/.agent/shared-repo-memory/post-turn-notify.py" --repo-root "$repo_root"
