#!/usr/bin/env bash
set -euo pipefail
exec python3 "$(dirname "$0")/scripts/shared-repo-memory/uninstall.py" "$@"
