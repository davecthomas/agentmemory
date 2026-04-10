#!/usr/bin/env bash
# runtime-log-prefix.sh -- Print the canonical shared-memory log prefix.
#
# Shell helpers and generated git hooks use this script so they emit the same
# runtime-aware prefix as the Python helpers:
#   [agentmemory][version=<agentmemory-version>][agent=<id>][provider-version=<version>]
#
# The underlying detection and version probing logic lives in common.py.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

if ! PYTHONPATH="$script_dir${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from common import format_log_prefix

print(format_log_prefix())
PY
then
  printf '%s\n' '[agentmemory][version=unknown][agent=unknown][provider-version=unknown]'
fi
