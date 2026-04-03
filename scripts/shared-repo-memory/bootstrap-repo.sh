#!/usr/bin/env bash
# bootstrap-repo.sh -- Backward-compatible wrapper for bootstrap-repo.py.
#
# The bootstrap logic now lives in bootstrap-repo.py so it can share utilities
# with the rest of the Python-based shared-memory system.  This wrapper exists
# only for callers that invoke the script by its original .sh name.
#
# Forwards all arguments unchanged (e.g., --dry-run) to the Python script.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

exec python3 "$script_dir/bootstrap-repo.py" "$@"
