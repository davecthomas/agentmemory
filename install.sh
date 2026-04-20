#!/usr/bin/env bash
# install.sh -- Install shared-repo-memory, or dispatch to uninstall.sh when
# the operator passes --uninstall. The --uninstall flag is stripped before the
# remaining arguments are forwarded, so flags like --dry-run, --repo, and
# --purge-memory pass through to uninstall.py verbatim.
set -euo pipefail

script_dir="$(dirname "$0")"

for arg in "$@"; do
    if [[ "$arg" == "--uninstall" ]]; then
        forwarded=()
        for a in "$@"; do
            [[ "$a" == "--uninstall" ]] || forwarded+=("$a")
        done
        exec python3 "$script_dir/scripts/shared-repo-memory/uninstall.py" "${forwarded[@]}"
    fi
done

exec python3 "$script_dir/scripts/shared-repo-memory/install.py" "$@"
