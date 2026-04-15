#!/usr/bin/env bash
# runtime-log-prefix.sh -- Print the canonical agentmemory log prefix.
#
# Shell helpers and generated git hooks use this script so they emit the same
# runtime-aware prefix as the Python helpers:
#   [agentmemory][version=<agentmemory-version>][runtime=<id>][runtime-version=<version>]
#
# The underlying detection and version probing logic lives in common.py.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

if ! PYTHONPATH="$script_dir${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from common import format_log_prefix

print(format_log_prefix())
PY
then
  str_version="$(
    sed -n 's/^SHARED_REPO_MEMORY_SYSTEM_VERSION: str = "\([^"]*\)"/\1/p' \
      "$script_dir/common.py" 2>/dev/null | head -n 1
  )"
  if [ -z "$str_version" ]; then
    str_version="unavailable"
  fi
  str_runtime_id="${AGENTMEMORY_RUNTIME_ID:-system}"
  str_runtime_version="${AGENTMEMORY_RUNTIME_VERSION:-n/a}"
  printf '%s\n' "[agentmemory][version=$str_version][runtime=$str_runtime_id][runtime-version=$str_runtime_version]"
fi
