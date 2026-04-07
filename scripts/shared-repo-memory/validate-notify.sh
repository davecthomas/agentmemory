#!/usr/bin/env bash
# validate-notify.sh -- Smoke-test the manual post-turn notify wrapper path.
#
# Sends a synthetic hook payload through notify-wrapper.sh and verifies that a
# new pending raw shard was created under .agents/memory/pending/<today>/.
#
# Use this script to confirm that post-turn-notify.py works when invoked
# directly through the wrapper, or when troubleshooting missing shards.
# This does NOT prove native Codex post-turn integration support.
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
#   0 -- validation succeeded; at least one new pending shard was created
#   1 -- validation failed; no new pending shard was created (check hook trace log)
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
log_prefix="$("$script_dir/runtime-log-prefix.sh")"

log() {
  echo "$log_prefix $*"
}

today="$(date +%F)"

# Count pending shards that exist before the validation run.
before_count=0
if [ -d ".agents/memory/pending/$today" ]; then
  before_count="$(find ".agents/memory/pending/$today" -maxdepth 1 -type f | wc -l | tr -d ' ')"
fi

# Build a synthetic payload that mimics what a real agent hook sends.
# The "files" field is included so parsers that look for it get a non-empty value,
# but the actual meaningful-turn gate uses `git status --porcelain`.
payload="$(cat <<'EOF'
{"thread_id":"notify-validation","turn_id":"notify-validation","prompt":"Validation: post-turn notify wiring is active for this repo and .agents/memory is the canonical shared memory path.","model":"gpt-5.4","summary_text":"Notify validation run. Verified repo-local wiring and installed shared post-turn assets.","files":["README.md"]}
EOF
)"

# Pipe the payload through notify-wrapper.sh to exercise the manual wrapper path.
printf '%s' "$payload" | ./scripts/shared-repo-memory/notify-wrapper.sh

# Count pending shards after the run; a successful notify increases the count by at least one.
after_count=0
if [ -d ".agents/memory/pending/$today" ]; then
  after_count="$(find ".agents/memory/pending/$today" -maxdepth 1 -type f | wc -l | tr -d ' ')"
fi

if [ "$after_count" -le "$before_count" ]; then
  log "notify-wrapper validation did not create a new pending shard" >&2
  log "check: do you have uncommitted tracked changes? (git status)" >&2
  log "check: tail ~/.agent/state/shared-repo-memory-hook-trace.jsonl" >&2
  exit 1
fi

log "notify-wrapper validation succeeded"
log "this confirms the manual wrapper path only; durable publication still requires enrichment"
