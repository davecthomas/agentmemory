#!/usr/bin/env bash
# install-user-assets.sh -- Shell-based installer for shared-repo-memory user assets.
#
# This script is an alternative to install.py that performs the same installation
# steps using only bash and Python one-liners (no third-party dependencies).
# It is called by install.sh when the Python installer is not available or
# when the user prefers the shell path.
#
# What this script does:
#   1. Creates ~/.agent/shared-repo-memory/ and copies helper scripts into it.
#   2. Updates ~/.codex/config.toml with required feature flags and hook config.
#   3. Writes ~/.codex/hooks.json with the SessionStart command hook.
#   4. Updates ~/.gemini/settings.json with SessionStart and AfterAgent hooks.
#
# Usage:
#   install-user-assets.sh [--dry-run]
#
# With --dry-run, every action is logged without modifying any file.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
log_prefix="$("$script_dir/runtime-log-prefix.sh")"

DRY_RUN=false
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --force)   FORCE=true ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
install_root="$HOME/.agent/shared-repo-memory"
codex_config="$HOME/.codex/config.toml"
hooks_config="$HOME/.codex/hooks.json"
gemini_config="$HOME/.gemini/settings.json"

log() {
  echo "$log_prefix $*"
}

# Create a directory if it does not already exist.
ensure_dir() {
  local path="$1"
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would create directory $path"
    return 0
  fi
  mkdir -p "$path"
}

# Append a line (with optional comment) to codex_config only when the pattern is absent.
# This prevents duplicate entries when re-running the installer.
append_line_if_missing() {
  local pattern="$1"
  local line="$2"
  local comment="${3:-}"
  if [ -f "$codex_config" ] && grep -Eq "$pattern" "$codex_config"; then
    return 0
  fi
  if [ "$DRY_RUN" = true ]; then
    if [ -n "$comment" ]; then
      log "[DRY-RUN] would append to $codex_config: # $comment"
    fi
    log "[DRY-RUN] would append to $codex_config: $line"
    return 0
  fi
  printf '\n' >> "$codex_config"
  if [ -n "$comment" ]; then
    printf '%s\n' "# $comment" >> "$codex_config"
  fi
  printf '%s\n' "$line" >> "$codex_config"
}

# Update a top-level TOML key=value line in-place, or append it when absent.
# Uses an inline Python script to handle the regex replacement reliably.
upsert_top_level_line() {
  local key="$1"
  local line="$2"
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would upsert in $codex_config: $line"
    return 0
  fi
  python3 - "$codex_config" "$key" "$line" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
key = sys.argv[2]
line = sys.argv[3]

text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
pattern = re.compile(rf'^{re.escape(key)}\s*=.*$', re.MULTILINE)
if pattern.search(text):
    updated = pattern.sub(line, text, count=1)
else:
    suffix = "" if not text or text.endswith("\n") else "\n"
    updated = f"{text}{suffix}\n{line}\n"
config_path.write_text(updated, encoding="utf-8")
PY
}

# Append the shared_agent_assets_repo_path key only when it is not present.
ensure_shared_agent_assets_repo_path() {
  if [ -f "$codex_config" ] && grep -Eq '^[[:space:]]*shared_agent_assets_repo_path[[:space:]]*=' "$codex_config"; then
    return 0
  fi
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would append to $codex_config: # Shared repo-memory authoring checkout used to refresh installed shared assets."
    log "[DRY-RUN] would append to $codex_config: shared_agent_assets_repo_path = \"$repo_root\""
    return 0
  fi
  printf '\n# Shared repo-memory authoring checkout used to refresh installed shared assets.\n' >> "$codex_config"
  printf 'shared_agent_assets_repo_path = "%s"\n' "$repo_root" >> "$codex_config"
}

# Append the shared_repo_memory_configured flag when absent.
ensure_shared_repo_memory_configured_flag() {
  append_line_if_missing \
    '^[[:space:]]*shared_repo_memory_configured[[:space:]]*=' \
    "shared_repo_memory_configured = true" \
    "Enable automatic shared repo-memory startup checks and repo bootstrap in Git repositories."
}

# Add a [projects."<path>"] trust block for this repo so Codex works without
# interactive approval prompts when editing files in the agentmemory checkout.
ensure_trusted_project_block() {
  if [ -f "$codex_config" ] && grep -Fq "[projects.\"$repo_root\"]" "$codex_config"; then
    return 0
  fi
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would append to $codex_config: # Trust this shared repo-memory authoring repo for local Codex work."
    log "[DRY-RUN] would append trusted project block for $repo_root to $codex_config"
    return 0
  fi
  printf '\n# Trust this shared repo-memory authoring repo for local Codex work.\n[projects."%s"]\ntrust_level = "trusted"\n' "$repo_root" >> "$codex_config"
}

# Write or merge the Codex hooks.json with the SessionStart command.
# Uses an inline Python script so JSON merging is correct regardless of existing content.
ensure_hooks_json() {
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would write $hooks_config with a SessionStart command hook"
    return 0
  fi
  python3 - "$hooks_config" "$HOME/.agent/shared-repo-memory/session-start.py" <<'PY'
import json
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
command = sys.argv[2]

payload = {"hooks": {}}
if hooks_path.exists():
    try:
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {"hooks": {}}

payload.setdefault("hooks", {})
payload["hooks"]["SessionStart"] = [
    {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 30,
            }
        ]
    }
]

hooks_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

# Write or merge ~/.gemini/settings.json with SessionStart and AfterAgent hooks.
# Uses an inline Python script so JSON merging is correct regardless of existing content.
ensure_gemini_settings_json() {
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would write Gemini settings to $gemini_config"
    return 0
  fi
  ensure_dir "$HOME/.gemini"
  python3 - "$gemini_config" "$repo_root" "$HOME/.agent/shared-repo-memory/session-start.py" "$HOME/.agent/shared-repo-memory/post-turn-notify.py" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
repo_root = sys.argv[2]
session_start_cmd = sys.argv[3]
post_turn_cmd = sys.argv[4]

payload = {}
if config_path.exists():
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}

payload["shared_agent_assets_repo_path"] = repo_root
payload["shared_repo_memory_configured"] = True

hooks = payload.setdefault("hooks", {})

# Add SessionStart hook if not already present (matched by hook name).
session_start_hooks = hooks.setdefault("SessionStart", [])
has_session_start = any(
    h.get("matcher") == "*" and any(sh.get("name") == "shared-repo-memory-session-start" for sh in h.get("hooks", []))
    for h in session_start_hooks
)
if not has_session_start:
    session_start_hooks.append({
        "matcher": "*",
        "hooks": [{
            "name": "shared-repo-memory-session-start",
            "type": "command",
            "command": session_start_cmd,
            "timeout": 30000
        }]
    })

# Add AfterAgent hook if not already present (matched by hook name).
after_agent_hooks = hooks.setdefault("AfterAgent", [])
has_after_agent = any(
    h.get("matcher") == "*" and any(sh.get("name") == "shared-repo-memory-post-turn" for sh in h.get("hooks", []))
    for h in after_agent_hooks
)
if not has_after_agent:
    after_agent_hooks.append({
        "matcher": "*",
        "hooks": [{
            "name": "shared-repo-memory-post-turn",
            "type": "command",
            "command": post_turn_cmd,
            "timeout": 30000
        }]
    })

config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

# Copy one skill directory into ~/.agent/skills/ and symlink it into each agent's
# skills directory.  Skips existing copies unless --force is passed.
install_skill() {
  local skill_name="$1"
  local skill_src="$repo_root/skills/$skill_name"
  local skill_dest="$HOME/.agent/skills/$skill_name"

  if [ ! -d "$skill_src" ]; then
    log "warning: skill directory not found: $skill_src"
    return 0
  fi

  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would copy skill $skill_name -> $skill_dest"
  elif [ -d "$skill_dest" ] && [ "$FORCE" = false ]; then
    log "skill $skill_name already installed (use --force to replace)"
  else
    if [ -d "$skill_dest" ] && [ "$FORCE" = true ]; then
      rm -rf "$skill_dest"
    fi
    cp -r "$skill_src" "$skill_dest"
    log "installed skill $skill_name -> $skill_dest"
  fi

  # Create per-agent symlinks pointing to the canonical copy.
  for agent_dir in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.gemini/skills"; do
    local link="$agent_dir/$skill_name"
    if [ "$DRY_RUN" = true ]; then
      log "[DRY-RUN] would symlink $link -> $skill_dest"
      continue
    fi
    mkdir -p "$agent_dir"
    if [ -L "$link" ]; then
      rm "$link"
    elif [ -e "$link" ]; then
      if [ "$FORCE" = true ]; then
        rm -rf "$link"
      else
        log "skipping symlink $link: already exists (use --force to replace)"
        continue
      fi
    fi
    ln -s "$skill_dest" "$link"
  done
}

# --- Main installation sequence ---

ensure_dir "$install_root"
ensure_dir "$HOME/.agent/state"
ensure_dir "$HOME/.agent/skills"
ensure_dir "$HOME/.codex"

# Copy each helper script into the install root and make it executable.
for file in \
  common.py \
  runtime-log-prefix.sh \
  bootstrap-repo.py \
  session-start.py \
  post-turn-notify.py \
  rebuild-summary.py \
  build-catchup.py \
  promote-adr.py
do
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] would copy $repo_root/scripts/shared-repo-memory/$file -> $install_root/$file"
  else
    cp "$repo_root/scripts/shared-repo-memory/$file" "$install_root/$file"
    chmod +x "$install_root/$file"
  fi
done

# Initialize refresh state file if absent (session-start.py requires it to exist).
refresh_state="$HOME/.agent/state/shared_asset_refresh_state.json"
if [ "$DRY_RUN" = true ]; then
  log "[DRY-RUN] would initialize refresh state at $refresh_state"
elif [ ! -f "$refresh_state" ]; then
  echo '{}' > "$refresh_state"
  log "initialized refresh state at $refresh_state"
fi

# Install skills from the repo's skills/ directory.
if [ -d "$repo_root/skills" ]; then
  for skill_dir in "$repo_root/skills"/*/; do
    install_skill "$(basename "$skill_dir")"
  done
else
  log "no skills/ directory found — skipping skill install"
fi

# Ensure config files exist before appending to them.
if [ "$DRY_RUN" = true ]; then
  log "[DRY-RUN] would ensure $codex_config exists"
  log "[DRY-RUN] would ensure $gemini_config exists"
else
  touch "$codex_config"
  touch "$gemini_config"
fi

# Wire Codex configuration.
ensure_shared_agent_assets_repo_path
ensure_shared_repo_memory_configured_flag
upsert_top_level_line "experimental_use_hooks" "experimental_use_hooks = true"
upsert_top_level_line "hooks_config_path" "hooks_config_path = \"$hooks_config\""
append_line_if_missing \
  '^[[:space:]]*features\.codex_hooks[[:space:]]*=' \
  "features.codex_hooks = true" \
  "Enable Codex hook execution so SessionStart can validate installed shared memory assets and ensure repo wiring."
ensure_trusted_project_block
ensure_hooks_json

# Wire Gemini configuration.
ensure_gemini_settings_json

log "installed helper files under $install_root"
log "updated Codex config at $codex_config"
log "Codex support status: SessionStart only. Native post-turn capture is not provisioned; notify-wrapper remains a manual smoke-test path."
log "updated hooks config at $hooks_config"
log "updated Gemini settings at $gemini_config"
