#!/usr/bin/env bash
set -euo pipefail

tmp_root="$(mktemp -d /tmp/shared-repo-memory-poc.XXXXXX)"
real_home="$HOME"
home_dir="$tmp_root/home"
source_repo="$tmp_root/source-repo"
remote="$tmp_root/remote.git"
install_clone="$tmp_root/install-clone"
clone_a="$tmp_root/clone-a"
clone_b="$tmp_root/clone-b"
sample_branch="sample-poc"
trace_path="$home_dir/.agent/state/shared-repo-memory-hook-trace.jsonl"
interrupted=0

cleanup_prompt() {
  local reason="$1"
  if [ ! -d "$tmp_root" ]; then
    return 0
  fi

  echo
  echo "Run did not complete successfully: $reason"
  echo "Temporary workspace: $tmp_root"

  if [ ! -t 0 ]; then
    echo "Interactive input is not available, so the temporary workspace was left in place."
    return 0
  fi

  while true; do
    printf 'Delete the temporary workspace now? [y/N] '
    read -r reply || return 0
    case "$reply" in
      [Yy]|[Yy][Ee][Ss])
        rm -rf "$tmp_root"
        echo "Deleted $tmp_root"
        return 0
        ;;
      ""|[Nn]|[Nn][Oo])
        echo "Kept $tmp_root"
        return 0
        ;;
      *)
        echo "Please answer y or n."
        ;;
    esac
  done
}

on_interrupt() {
  interrupted=1
  exit 130
}

on_exit() {
  local status="$1"
  set +e
  if [ "$status" -eq 0 ]; then
    return 0
  fi
  if [ "$interrupted" -eq 1 ]; then
    cleanup_prompt "interrupted by the operator"
  else
    cleanup_prompt "exited with status $status"
  fi
}

trap 'on_interrupt' INT TERM
trap 'on_exit $?' EXIT

prompt_continue() {
  local next_step="${1:-the next step}"
  printf '\nPress Enter to proceed to %s...' "$next_step"
  read -r _
}

step_header() {
  local number="$1"
  local title="$2"
  local purpose="$3"
  local expected="$4"
  echo
  echo "Step $number: $title"
  echo "Purpose:"
  echo "  $purpose"
  echo "Expected evidence:"
  echo "  $expected"
}

run_cmd() {
  echo "  $*"
  "$@"
}

require_path() {
  local path="$1"
  if [ ! -e "$path" ]; then
    echo "ERROR: expected path does not exist: $path" >&2
    exit 1
  fi
}

require_missing_path() {
  local path="$1"
  if [ -e "$path" ]; then
    echo "ERROR: expected path to be absent before SessionStart bootstrap: $path" >&2
    exit 1
  fi
}

require_symlink_target() {
  local path="$1"
  local expected="$2"
  local actual
  if [ ! -L "$path" ]; then
    echo "ERROR: expected symlink but found something else: $path" >&2
    exit 1
  fi
  actual="$(readlink "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "ERROR: expected $path -> $expected but found $actual" >&2
    exit 1
  fi
}

print_preview() {
  local label="$1"
  local path="$2"
  local lines="${3:-20}"
  echo "$label: $path"
  sed -n "1,${lines}p" "$path"
}

build_source_snapshot() {
  mkdir -p "$source_repo"
  rsync -a --exclude '.git' --exclude '.DS_Store' --exclude '.codex/local' ./ "$source_repo"/
  git -C "$source_repo" init -b main >/dev/null
  git -C "$source_repo" config user.name "POC Snapshot"
  git -C "$source_repo" config user.email "poc-snapshot@example.com"
  git -C "$source_repo" add -A
  git -C "$source_repo" commit -m "POC source snapshot" >/dev/null
}

resolve_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve())
PY
}

seed_codex_auth() {
  if [ ! -f "$real_home/.codex/auth.json" ]; then
    echo "ERROR: missing $real_home/.codex/auth.json; log into Codex first." >&2
    exit 1
  fi
  mkdir -p "$home_dir/.codex"
  cp "$real_home/.codex/auth.json" "$home_dir/.codex/auth.json"
}

ensure_trusted_project() {
  local repo_path="$1"
  local config_path="$home_dir/.codex/config.toml"
  if grep -Fq "[projects.\"$repo_path\"]" "$config_path"; then
    return 0
  fi
  printf '\n[projects."%s"]\ntrust_level = "trusted"\n' "$repo_path" >> "$config_path"
}

trace_count() {
  local hook="$1"
  local status="$2"
  local repo_path="$3"
  python3 - "$trace_path" "$hook" "$status" "$repo_path" <<'PY'
import json
import sys
from pathlib import Path

trace_path = Path(sys.argv[1])
hook = sys.argv[2]
status = sys.argv[3]
repo_path = sys.argv[4]

count = 0
if trace_path.exists():
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("hook") != hook:
            continue
        if status != "*" and item.get("status") != status:
            continue
        if repo_path != "*" and item.get("repo_root") != repo_path:
            continue
        count += 1
print(count)
PY
}

echo "Interactive shared repo memory POC"
echo "Temporary workspace: $tmp_root"
echo "This script uses real Codex sessions for SessionStart and post-turn notify in a disposable clone."
echo "It proves hook execution with durable JSONL breadcrumbs under $trace_path instead of relying only on terminal output."
prompt_continue "Step 1 (create the disposable remote and clones)"

mkdir -p "$home_dir"

clone_a_resolved="$(resolve_path "$clone_a")"
clone_b_resolved="$(resolve_path "$clone_b")"

step_header \
  "1" \
  "Snapshot the current working tree, then create a bare remote and three working clones" \
  "Capture the live working tree, including uncommitted changes, into a disposable source repo so the test runs against exactly what is on disk right now. Then simulate one install-only working copy, one live Codex working copy that must bootstrap itself through SessionStart, and one consumer clone that rebuilds catch-up through Git hooks after the push." \
  "A disposable source repo at $source_repo, a bare remote at $remote, plus working clones at $install_clone, $clone_a, and $clone_b."
run_cmd build_source_snapshot
run_cmd git clone --bare "$source_repo" "$remote"
run_cmd git clone "$remote" "$install_clone"
run_cmd git clone "$remote" "$clone_a"
run_cmd git clone "$remote" "$clone_b"
echo "Source snapshot HEAD: $(git -C "$source_repo" rev-parse --short HEAD)"
echo "Install clone HEAD: $(git -C "$install_clone" rev-parse --abbrev-ref HEAD)"
echo "Clone A HEAD: $(git -C "$clone_a" rev-parse --abbrev-ref HEAD)"
echo "Clone B HEAD: $(git -C "$clone_b" rev-parse --abbrev-ref HEAD)"
prompt_continue "Step 2 (seed a disposable Codex HOME and install shared assets)"

step_header \
  "2" \
  "Seed a disposable Codex HOME and run the supported installer once" \
  "Copy the current Codex auth token into a disposable HOME, then run install.sh in the install-only clone so the shared skills, installed helper scripts, SessionStart hook registration, refresh state, and disposable-home config are all created without pre-bootstrapping clone A." \
  "The disposable HOME has auth.json, ~/.agent/shared-repo-memory/*, ~/.agent/state/shared_asset_refresh_state.json, ~/.codex/skills/memory-writer, experimental_use_hooks plus hooks_config_path in ~/.codex/config.toml, and a SessionStart command hook in ~/.codex/hooks.json."
seed_codex_auth
(
  cd "$install_clone"
  run_cmd env HOME="$home_dir" ./install.sh
)
require_path "$home_dir/.codex/auth.json"
require_path "$home_dir/.agent/shared-repo-memory/post-turn-notify.py"
require_path "$home_dir/.agent/state/shared_asset_refresh_state.json"
require_path "$home_dir/.codex/skills/memory-writer"
require_path "$home_dir/.codex/skills/adr-promoter"
require_path "$home_dir/.codex/hooks.json"
grep -q '^shared_repo_memory_configured = true$' "$home_dir/.codex/config.toml"
grep -q '^experimental_use_hooks = true$' "$home_dir/.codex/config.toml"
grep -q '^hooks_config_path = "'"$home_dir"'/.codex/hooks.json"$' "$home_dir/.codex/config.toml"
grep -q '"SessionStart"' "$home_dir/.codex/hooks.json"
grep -q "$home_dir/.agent/shared-repo-memory/session-start.py" "$home_dir/.codex/hooks.json"
prompt_continue "Step 3 (trust the live and consumer clones without bootstrapping them)"

step_header \
  "3" \
  "Trust the live and consumer clones without bootstrapping them" \
  "Teach the disposable Codex HOME to trust clone A and clone B so repo-local .codex/config.toml notify wiring can load there, while intentionally leaving clone A unwired so SessionStart must do the real bootstrap work." \
  "Clone A is trusted, but .codex/local is absent and git core.hooksPath is unset before the first live Codex run."
ensure_trusted_project "$clone_a"
ensure_trusted_project "$clone_b"
ensure_trusted_project "$clone_a_resolved"
ensure_trusted_project "$clone_b_resolved"
require_missing_path "$clone_a/.codex/local"
if [ -n "$(git -C "$clone_a" config --get core.hooksPath || true)" ]; then
  echo "ERROR: expected clone A core.hooksPath to be unset before the first live SessionStart run" >&2
  exit 1
fi
echo "Verified clone A starts unwired:"
echo "  .codex/local absent"
echo "  core.hooksPath unset"
prompt_continue "Step 4 (run a real Codex session in clone A to trigger SessionStart)"

step_header \
  "4" \
  "Run a real interactive Codex session in clone A and prove SessionStart bootstrapped the repo" \
  "Start the interactive Codex CLI itself in the unwired clone from another terminal window. SessionStart is the startup hook under test, so this step must use a real interactive session rather than codex exec." \
  "The trace file gains a SessionStart success entry for clone A, clone A now has .codex/local, .codex/memory -> ../.agents/memory, and git core.hooksPath is .githooks."
sessionstart_before="$(trace_count "SessionStart" "success" "$clone_a_resolved")"
echo "Run this command in another terminal, then exit Codex and return here:"
echo "  env HOME=\"$home_dir\" codex --no-alt-screen -C \"$clone_a\""
prompt_continue "the SessionStart verification after you have started and exited interactive Codex in clone A"
sessionstart_after="$(trace_count "SessionStart" "success" "$clone_a_resolved")"
if [ "$sessionstart_after" -le "$sessionstart_before" ]; then
  echo "ERROR: expected a new SessionStart success trace entry for clone A" >&2
  exit 1
fi
require_path "$clone_a/.codex/local"
require_symlink_target "$clone_a/.codex/memory" "../.agents/memory"
if [ "$(git -C "$clone_a" config --get core.hooksPath)" != ".githooks" ]; then
  echo "ERROR: expected clone A core.hooksPath to be .githooks after SessionStart" >&2
  exit 1
fi
echo "Recent hook trace entries:"
tail -n 4 "$trace_path"
prompt_continue "Step 5 (run a real meaningful interactive Codex turn in clone A)"

step_header \
  "5" \
  "Run a real meaningful interactive Codex turn in clone A and prove notify wrote memory" \
  "Start Codex interactively in clone A again, ask it to create one tracked repo change that states the durable decision under test, and explicitly forbid it from touching .agents or .codex so any resulting memory artifacts must come from the Notify hook rather than from the model directly." \
  "Clone A gains docs/poc-script-output.md, clone A/.codex/local/last-notify-payload.json exists, the trace file gains a Notify success entry for clone A, and .agents/memory/daily/<date>/events plus summary.md update in clone A."
notify_before="$(trace_count "Notify" "success" "$clone_a_resolved")"
echo "Run this command in another terminal:"
echo "  env HOME=\"$home_dir\" codex --no-alt-screen -C \"$clone_a\""
echo "Then give Codex this exact prompt, wait for the turn to finish, exit Codex, and return here:"
cat <<'EOF'
Create docs/poc-script-output.md containing a short note that .agents/memory remains the canonical shared memory path and .codex/memory is only a symlink. Treat that statement as a durable repo decision. Do not stage or commit anything. Do not read, write, or stage any files under .agents/ or .codex/.
EOF
prompt_continue "the Notify verification after the meaningful interactive Codex turn in clone A"
notify_after="$(trace_count "Notify" "success" "$clone_a_resolved")"
if [ "$notify_after" -le "$notify_before" ]; then
  echo "ERROR: expected a new Notify success trace entry for clone A" >&2
  exit 1
fi
require_path "$clone_a/docs/poc-script-output.md"
require_path "$clone_a/.codex/local/last-notify-payload.json"
shard_path="$(find "$clone_a/.agents/memory/daily" -path '*/events/*.md' | sort | tail -n1)"
require_path "$shard_path"
date_dir="$(basename "$(dirname "$(dirname "$shard_path")")")"
summary_path="$clone_a/.agents/memory/daily/$date_dir/summary.md"
require_path "$summary_path"
prompt_continue "Step 6 (inspect the hook traces and generated memory artifacts)"

step_header \
  "6" \
  "Inspect the durable hook evidence and generated memory artifacts" \
  "Show the actual trace entries and memory files so the operator can verify that real hooks, not manual script invocations, produced the repo-local bootstrap and the event write." \
  "The trace preview shows SessionStart success and Notify success for clone A, and the shard frontmatter plus summary headings look correct."
echo "Trace preview: $trace_path"
tail -n 8 "$trace_path"
echo
print_preview "Shard preview" "$shard_path" 28
echo
print_preview "Summary preview" "$summary_path" 28
echo
echo "Files currently staged after the real notify run:"
git -C "$clone_a" diff --cached --name-only
prompt_continue "Step 7 (bootstrap the consumer clone for Git-hook catch-up)"

step_header \
  "7" \
  "Prepare the consumer clone for Git-hook catch-up" \
  "Run the supported installer in clone B so its local Git hooks and .codex/local state exist before it fetches the published memory-bearing commit from clone A." \
  "Clone B reports repository setup complete, .codex/memory -> ../.agents/memory, and git core.hooksPath = .githooks."
(
  cd "$clone_b"
  run_cmd env HOME="$home_dir" ./install.sh
)
require_symlink_target "$clone_b/.codex/memory" "../.agents/memory"
if [ "$(git -C "$clone_b" config --get core.hooksPath)" != ".githooks" ]; then
  echo "ERROR: expected clone B core.hooksPath to be .githooks after install" >&2
  exit 1
fi
prompt_continue "Step 8 (commit and push from clone A)"

step_header \
  "8" \
  "Commit the tracked repo change and generated memory files together, then push them" \
  "Publish the meaningful change plus generated memory so clone B can consume the shared update through its Git hooks." \
  "git commit creates one commit containing docs/poc-script-output.md plus the generated shard and summary, and git push publishes branch $sample_branch."
(
  cd "$clone_a"
  run_cmd git config user.name "POC Script"
  run_cmd git config user.email "poc-script@example.com"
  run_cmd git commit -m "POC interactive run"
  run_cmd git push origin HEAD:"$sample_branch"
)
prompt_continue "Step 9 (consume the pushed branch in clone B)"

step_header \
  "9" \
  "Fetch the published branch in clone B and let the Git hook rebuild catch-up" \
  "Move clone B onto the published branch so the repository's post-checkout hook rebuilds local catch-up from the shared memory without manual catch-up execution." \
  "The checkout path prints [shared-repo-memory] catch-up rebuilt via post-checkout, .codex/local/catchup.md exists, and that file references the new summary or shard."
(
  cd "$clone_b"
  run_cmd env HOME="$home_dir" git fetch origin "$sample_branch"
  run_cmd env HOME="$home_dir" git checkout -B "$sample_branch" FETCH_HEAD
)
catchup_path="$clone_b/.codex/local/catchup.md"
sync_state_path="$clone_b/.codex/local/sync_state.json"
require_path "$catchup_path"
require_path "$sync_state_path"
echo
print_preview "Catch-up preview" "$catchup_path" 28
echo
print_preview "Catch-up sync state" "$sync_state_path" 20
prompt_continue "Step 10 (prove summary rebuild determinism)"

step_header \
  "10" \
  "Rebuild the same summary again and compare checksums" \
  "Prove the summary renderer is deterministic when the shard inputs are unchanged." \
  "The before and after SHA-256 checksums match exactly."
before_checksum="$(shasum -a 256 "$summary_path" | awk '{print $1}')"
echo "Before rebuild checksum: $before_checksum"
(
  cd "$clone_a"
  run_cmd env HOME="$home_dir" ./scripts/shared-repo-memory/rebuild-summary.py --repo-root "$clone_a" --date "$date_dir"
)
after_checksum="$(shasum -a 256 "$summary_path" | awk '{print $1}')"
echo "After rebuild checksum:  $after_checksum"
if [ "$before_checksum" != "$after_checksum" ]; then
  echo "ERROR: summary rebuild was not deterministic" >&2
  exit 1
fi
echo "Determinism check passed."
prompt_continue "Step 11 (promote the decision shard to an ADR)"

step_header \
  "11" \
  "Promote the decision-candidate shard to an ADR" \
  "Exercise the explicit ADR workflow so the decision shard becomes a durable ADR and the ADR index refreshes." \
  "The promoter prints the new ADR path, a new ADR-XXXX markdown file exists, and .agents/memory/adr/INDEX.md lists that ADR."
(
  cd "$clone_a"
  run_cmd env HOME="$home_dir" ./scripts/shared-repo-memory/promote-adr.sh "$shard_path"
)
adr_path="$(find "$clone_a/.agents/memory/adr" -name 'ADR-*.md' | sort | tail -n1)"
adr_index="$clone_a/.agents/memory/adr/INDEX.md"
require_path "$adr_path"
require_path "$adr_index"
echo
print_preview "ADR preview" "$adr_path" 24
echo
print_preview "ADR index preview" "$adr_index" 20

echo
echo "POC completed successfully."
echo "Artifacts to inspect:"
echo "  durable hook trace:                    $trace_path"
echo "  install clone:                         $install_clone"
echo "  first real Codex clone repo change:    $clone_a/docs/poc-script-output.md"
echo "  first real Codex clone shard:          $shard_path"
echo "  first real Codex clone summary:        $summary_path"
echo "  first real Codex clone ADR:            $adr_path"
echo "  second clone catch-up:                 $catchup_path"
echo "  second clone sync state:               $sync_state_path"
echo
echo "Temporary workspace retained at: $tmp_root"
echo "Delete it manually when you are done inspecting the disposable clones."
