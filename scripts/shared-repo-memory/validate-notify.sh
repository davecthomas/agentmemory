#!/usr/bin/env bash
# validate-notify.sh -- Smoke-test the post-turn notify path end-to-end.
#
# Sends a synthetic hook payload through notify-wrapper.sh (the same path a
# live Codex agent turn uses) and verifies that a new event shard was created
# under .agents/memory/daily/<today>/events/.
#
# Use this script after installation to confirm the wiring is working, or when
# troubleshooting missing shards.
#
# Note: this script uses README.md as the "files_touched" signal in the payload.
# The meaningful-turn gate in post-turn-notify.py requires at least one tracked
# file with uncommitted changes.  Run this when README.md has uncommitted edits,
# or after making any other tracked change to the repo.
#
# Usage:
#   ./scripts/shared-repo-memory/validate-notify.sh
#
# Exit codes:
#   0 -- validation succeeded; at least one new shard was created
#   1 -- validation failed; no new shard was created (check hook trace log)
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

today="$(date +%F)"

# Count shards that exist before the validation run.
before_count=0
if [ -d ".agents/memory/daily/$today/events" ]; then
  before_count="$(find ".agents/memory/daily/$today/events" -maxdepth 1 -type f | wc -l | tr -d ' ')"
fi

# Build a synthetic payload that mimics what a real agent hook sends.
# The "files" field is included so parsers that look for it get a non-empty value,
# but the actual meaningful-turn gate uses `git status --porcelain`.
payload="$(cat <<'EOF'
{"thread_id":"notify-validation","turn_id":"notify-validation","prompt":"Validation: post-turn notify wiring is active for this repo and .agents/memory is the canonical shared memory path.","model":"gpt-5.4","summary_text":"Notify validation run. Verified repo-local wiring and installed shared post-turn assets.","files":["README.md"]}
EOF
)"

# Pipe the payload through notify-wrapper.sh exactly as a real Codex turn would.
printf '%s' "$payload" | ./scripts/shared-repo-memory/notify-wrapper.sh

# Count shards after the run; a successful notify increases the count by at least one.
after_count=0
if [ -d ".agents/memory/daily/$today/events" ]; then
  after_count="$(find ".agents/memory/daily/$today/events" -maxdepth 1 -type f | wc -l | tr -d ' ')"
fi

if [ "$after_count" -le "$before_count" ]; then
  echo "[shared-repo-memory] notify validation did not create a new event shard" >&2
  echo "[shared-repo-memory] check: do you have uncommitted tracked changes? (git status)" >&2
  echo "[shared-repo-memory] check: tail ~/.agent/state/shared-repo-memory-hook-trace.jsonl" >&2
  exit 1
fi

echo "[shared-repo-memory] notify validation succeeded"
echo "[shared-repo-memory] restart the current Codex session if live turns still are not writing memory"
