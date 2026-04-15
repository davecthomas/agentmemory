#!/usr/bin/env python3
"""session-start.py -- SessionStart hook for the shared repo-memory system.

This script runs at every agent session open via the SessionStart hook.  Its job
is to ensure the shared memory infrastructure is healthy and then inject the
current memory context (ADR index + recent daily summaries) into the opening
agent context so the model starts the session with institutional knowledge rather
than a blank slate.

Execution path:
  1. Read hook payload from stdin (may be empty or a JSON object).
  2. Check shared_repo_memory_configured flag -- exit silently if disabled.
  3. Verify installed helper scripts and skills exist under ~/.agent/.
  4. Detect the current git repo root from the working directory.
  5. Inspect repo wiring; call bootstrap-repo.py to create any missing dirs or
     symlinks.
  6. Load ADR index + recent daily summaries as a single memory_context string.
  7. Output in the format appropriate for the calling agent:
       - Claude Code: {"systemMessage": ..., "hookSpecificOutput": {...}}
       - Codex / Gemini: flat {"status": "ok", "memory_context": ..., ...}

Agent detection:
  CLAUDECODE=1 env var is set by Claude Code for every hook invocation.  This
  is more reliable than inspecting the hook event name in the payload because
  Stop events and SessionStart events both share the same env var.

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/session-start.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TextIO

from adapters import detect_adapter
from common import (
    append_hook_trace,
    format_log_prefix,
    load_json,
    missing_gitignore_entries,
    runtime_provider_version,
    safe_main,
    set_runtime_log_context,
    warn,
)
from models import SessionResponse

# Expected relative target for the .codex/memory -> .agents/memory symlink.
# bootstrap-repo.py creates this symlink; session-start.py validates it.
EXPECTED_MEMORY_TARGET = "../.agents/memory"
REQUIRED_GIT_HOOKS: tuple[str, ...] = (
    "pre-commit",
    "post-checkout",
    "post-merge",
    "post-rewrite",
)

# Config key checked in ~/.claude/settings.json and ~/.codex/config.toml.
# The SessionStart hook exits silently when this key is absent or false,
# so the system can be installed without modifying repos that have not opted in.
SESSION_START_FLAG = "shared_repo_memory_configured"


def emit_session_response(
    system_message: str,
    additional_context: str = "",
    *,
    continue_session: bool = True,
) -> None:
    """Print a SessionStart hook response using the detected runtime adapter.

    Args:
        system_message: Short status text shown in the agent UI.
        additional_context: Memory text injected into the model context before
            the first turn.  Empty string omits the field.
        continue_session: When False, signals the agent to abort the session.
    """
    adapter = detect_adapter()
    set_runtime_log_context(adapter.agent_id())
    resp = SessionResponse(
        system_message=system_message,
        additional_context=additional_context,
        continue_session=continue_session,
    )
    print(adapter.render_session_response(resp))


def load_toml(path: Path) -> dict:
    """Load and return a TOML file as a plain dict, returning {} on any error.

    Args:
        path: Path to a .toml config file.

    Returns:
        dict: Parsed TOML contents, or empty dict if the file is absent or invalid.
    """
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        warn(f"SessionStart could not parse {path}: {error}")
        return {}


def load_claude_settings(path: Path) -> dict:
    """Load and return Claude Code settings.json as a plain dict.

    Args:
        path: Path to ~/.claude/settings.json.

    Returns:
        dict: Parsed JSON contents, or empty dict if the file is absent or invalid.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        warn(f"SessionStart could not parse {path}: {error}")
        return {}


def is_memory_configured(home: Path) -> bool:
    """Return True if shared repo memory is enabled in any supported agent config.

    Checks both ~/.codex/config.toml and ~/.claude/settings.json for the
    SESSION_START_FLAG key.  A single True value in either file is sufficient
    to activate the system for the current session.

    Args:
        home: User home directory (typically Path.home()).

    Returns:
        bool: True if shared_repo_memory_configured is truthy in at least one
            agent config; False otherwise.
    """
    codex_config = load_toml(home / ".codex" / "config.toml")
    if codex_config.get(SESSION_START_FLAG, False):
        return True
    claude_settings = load_claude_settings(home / ".claude" / "settings.json")
    if claude_settings.get(SESSION_START_FLAG, False):
        return True
    return False


def current_repo_root(cwd: Path) -> Path | None:
    """Return the git repo root for cwd, or None when not inside a git repo.

    Uses git rev-parse rather than searching for .git directly so that
    worktrees and submodules are handled correctly.

    Args:
        cwd: Directory to start the search from.

    Returns:
        Path | None: Resolved absolute path to the repo root, or None.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def repo_wiring_issues(repo_root: Path) -> list[str]:
    """Return a list of paths that are missing or misconfigured for shared memory.

    Expected repo-local structure:
      .agents/memory/adr/       -- ADR storage directory
      .agents/memory/daily/     -- daily shard storage directory
      .agents/memory/pending/   -- ignored raw shard staging directory
      .agents/memory/state/     -- ignored derived episode-graph state
      .codex/local/             -- local catch-up state (not committed)
      .githooks/                -- git hooks directory
      .githooks/pre-commit      -- blocks commits of raw/pending shards
      .githooks/post-checkout   -- rebuilds local catch-up after checkout
      .githooks/post-merge      -- rebuilds local catch-up after merge/pull
      .githooks/post-rewrite    -- rebuilds local catch-up after rebase/rewrite
      .agents/memory/adr/INDEX.md   -- ADR index file
      .codex/memory             -- symlink to ../.agents/memory
      .gitignore                -- contains required local-state ignore entries
      git config core.hooksPath == ".githooks"

    The session-start hook calls bootstrap-repo.py to repair any gaps, then
    re-checks this list to confirm the bootstrap succeeded.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        list[str]: Human-readable descriptions of each missing or wrong item.
            Empty list means the repo is fully wired.
    """
    issues: list[str] = []
    repo_memory_root = repo_root / ".agents" / "memory"
    repo_memory_adr = repo_memory_root / "adr"
    repo_memory_daily = repo_memory_root / "daily"
    repo_memory_pending = repo_memory_root / "pending"
    repo_memory_state = repo_memory_root / "state"
    codex_local = repo_root / ".codex" / "local"
    githooks = repo_root / ".githooks"
    repo_memory_link = repo_root / ".codex" / "memory"
    adr_index = repo_memory_adr / "INDEX.md"

    if not repo_memory_adr.is_dir():
        issues.append(str(repo_memory_adr))
    if not repo_memory_daily.is_dir():
        issues.append(str(repo_memory_daily))
    if not repo_memory_pending.is_dir():
        issues.append(str(repo_memory_pending))
    if not repo_memory_state.is_dir():
        issues.append(str(repo_memory_state))
    if not codex_local.is_dir():
        issues.append(str(codex_local))
    if not githooks.is_dir():
        issues.append(str(githooks))
    # Ensure each required Git hook exists, not just the parent directory.
    for str_hook_name in REQUIRED_GIT_HOOKS:
        hook_path: Path = githooks / str_hook_name
        if not hook_path.is_file():
            issues.append(str(hook_path))
    if not adr_index.is_file():
        issues.append(str(adr_index))
    # Validate the symlink: must exist as a symlink and point to the canonical target.
    if not repo_memory_link.is_symlink():
        issues.append(str(repo_memory_link))
    elif repo_memory_link.readlink().as_posix() != EXPECTED_MEMORY_TARGET:
        issues.append(f"{repo_memory_link} -> {EXPECTED_MEMORY_TARGET}")

    # Verify git's hooksPath so that post-checkout, post-merge, etc. fire correctly.
    hooks_path = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if hooks_path != ".githooks":
        issues.append(f"{repo_root}/.git config core.hooksPath = .githooks")

    list_str_missing_gitignore_entries: list[str] = missing_gitignore_entries(repo_root)
    if list_str_missing_gitignore_entries:
        issues.append(
            f"{repo_root}/.gitignore missing shared repo-memory ignore entries: "
            + ", ".join(list_str_missing_gitignore_entries)
        )

    return issues


def load_memory_context(repo_root: Path) -> str:
    """Build and return the memory context block injected into the agent at session start.

    Combines two sources in priority order:
      1. .agents/memory/adr/INDEX.md -- full ADR index table.
      2. The three most recent daily summary.md files (newest first).

    Keeping the context bounded to 3 days prevents the payload from growing
    unboundedly in long-running repos.  The ADR index covers architectural
    decisions that persist across days.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        str: Markdown-formatted context block ready for injection, or empty string
            if no memory files exist yet.
    """
    sections: list[str] = []

    # Always include the ADR index when present -- it is the most durable context.
    adr_index = repo_root / ".agents" / "memory" / "adr" / "INDEX.md"
    if adr_index.exists():
        sections.append(
            "### Architecture Decision Records\n\n"
            + adr_index.read_text(encoding="utf-8").strip()
        )

    # Append recent daily summaries, most recent first.
    daily_root = repo_root / ".agents" / "memory" / "daily"
    if daily_root.exists():
        recent_days = sorted(
            (d for d in daily_root.iterdir() if d.is_dir()),
            reverse=True,
        )[:3]
        for day_dir in recent_days:
            summary = day_dir / "summary.md"
            if summary.exists():
                sections.append(
                    f"### Memory: {day_dir.name}\n\n"
                    + summary.read_text(encoding="utf-8").strip()
                )

    return "\n\n".join(sections) if sections else ""


def run_repo_bootstrap(helper_path: Path, repo_root: Path) -> bool:
    """Run bootstrap-repo.py to create missing repo-local wiring.

    bootstrap-repo.py is idempotent -- running it on an already-wired repo is
    safe.  Both stdout and stderr from the subprocess are forwarded to warn()
    so they appear in the agent's stderr stream rather than the hook's stdout.
    This is critical: any non-JSON text on the hook's stdout would cause Codex
    and Claude Code to reject the hook response as invalid JSON.

    Args:
        helper_path: Absolute path to the installed bootstrap-repo.py script.
        repo_root: Absolute path to the repository to bootstrap.

    Returns:
        bool: True if bootstrap-repo.py exited 0; False otherwise.
    """
    result = subprocess.run(
        [str(helper_path)],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    # Forward all subprocess output to stderr only -- never to stdout.
    # The hook's stdout must contain only the final JSON response.
    for line in (result.stdout + result.stderr).splitlines():
        if line.strip():
            warn(line.strip())
    if result.returncode != 0:
        warn(f"SessionStart repo bootstrap failed in {repo_root}")
        return False
    return True


def _acquire_lock(repo_root: Path, ttl: int = 300) -> bool:
    """Acquire the bootstrap lock. Return False if already locked by a recent process."""
    import time

    lock = repo_root / ".agents" / "memory" / ".auto_bootstrap_running"
    if lock.exists() and (time.time() - lock.stat().st_mtime) < ttl:
        return False
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    return True


def _release_lock(repo_root: Path) -> None:
    """Remove the bootstrap lock file so a fallback or retry can proceed.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        None: Missing locks are ignored.
    """
    lock: Path = repo_root / ".agents" / "memory" / ".auto_bootstrap_running"
    lock.unlink(missing_ok=True)


def _open_bootstrap_log(repo_root: Path) -> TextIO:
    """Open (or create) the bootstrap log file and return the file object."""
    log_dir = repo_root / ".agents" / "memory" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return open(log_dir / "bootstrap.log", "a")  # noqa: SIM115


def _write_bootstrap_log_line(
    log_file: TextIO,
    *,
    str_launcher_runtime_id: str,
    str_launcher_runtime_version: str,
    str_message: str,
) -> None:
    """Write one agentmemory-prefixed bootstrap log line.

    Args:
        log_file: Open bootstrap log handle.
        str_launcher_runtime_id: Runtime id associated with this bootstrap path.
        str_launcher_runtime_version: Resolved CLI version for that runtime.
        str_message: Human-readable bootstrap log message suffix.

    Returns:
        None: One line is appended and flushed immediately.
    """
    log_file.write(
        f"{format_log_prefix(str_launcher_runtime_id, str_launcher_runtime_version)} "
        f"{str_message}\n"
    )
    log_file.flush()


def _spawn_subagent_bootstrap(repo_root: Path) -> bool:
    """Spawn a subagent to run memory bootstrap using the detected runtime adapter.

    The subagent receives the full SKILL.md content as its system prompt and a short
    user message as the task.  It runs with a clean context (no conversation history),
    which prevents the reasoning-around-instructions failure mode seen when bootstrap
    instructions are injected into the main agent's context.

    This path never falls back to another provider. If the current runtime does
    not expose a supported non-interactive bootstrap command, SessionStart
    leaves bootstrap manual so agentmemory never presumes Claude or Anthropic
    credentials in another runtime.

    Returns True if a process was launched, False if skipped.
    """
    if not _acquire_lock(repo_root):
        return False

    skill_path = Path.home() / ".agent" / "skills" / "memory-bootstrap" / "SKILL.md"
    adapter = detect_adapter()
    str_launcher_runtime_id: str = adapter.agent_id()
    str_launcher_runtime_version: str = runtime_provider_version(
        str_launcher_runtime_id
    )

    if not skill_path.exists():
        _release_lock(repo_root)
        return False

    skill_content = skill_path.read_text(encoding="utf-8")
    task = "Bootstrap agentmemory from recent commits and design docs."
    cmd = adapter.build_bootstrap_command(skill_content, task, repo_root)
    if cmd is None:
        log_file = _open_bootstrap_log(repo_root)
        try:
            _write_bootstrap_log_line(
                log_file,
                str_launcher_runtime_id=str_launcher_runtime_id,
                str_launcher_runtime_version=str_launcher_runtime_version,
                str_message=(
                    "background bootstrap skipped: current runtime does not expose "
                    "a supported non-interactive bootstrap command; run "
                    "/memory-bootstrap manually"
                ),
            )
        finally:
            log_file.close()
        _release_lock(repo_root)
        return False

    log_file = _open_bootstrap_log(repo_root)
    try:
        _write_bootstrap_log_line(
            log_file,
            str_launcher_runtime_id=str_launcher_runtime_id,
            str_launcher_runtime_version=str_launcher_runtime_version,
            str_message=f"starting bootstrap via {cmd[0]}",
        )
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=log_file,
            stderr=log_file,
            env={
                **os.environ,
                "AGENTMEMORY_RUNTIME_ID": str_launcher_runtime_id,
                "AGENTMEMORY_RUNTIME_VERSION": str_launcher_runtime_version,
                "SHARED_REPO_MEMORY_AGENT_ID": str_launcher_runtime_id,
                "SHARED_REPO_MEMORY_PROVIDER_VERSION": (str_launcher_runtime_version),
            },
            start_new_session=True,
        )
        return True
    except OSError as error:
        _write_bootstrap_log_line(
            log_file,
            str_launcher_runtime_id=str_launcher_runtime_id,
            str_launcher_runtime_version=str_launcher_runtime_version,
            str_message=(
                f"bootstrap launch failed for {str_launcher_runtime_id}: {error}. "
                "Run /memory-bootstrap manually."
            ),
        )
        warn(
            f"SessionStart: {str_launcher_runtime_id} bootstrap launch failed; manual /memory-bootstrap required"
        )
        _release_lock(repo_root)
        return False
    finally:
        log_file.close()


def _spawn_auto_bootstrap(repo_root: Path) -> bool:
    """Legacy fallback: spawn auto-bootstrap.py as a detached background process.

    This helper is retained only for explicit legacy compatibility. Agentmemory
    does not require ANTHROPIC_API_KEY and SessionStart no longer invokes this
    path automatically.

    Returns True if the process was launched, False if skipped.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    if not _acquire_lock(repo_root):
        return False
    script: Path = Path(__file__).parent / "auto-bootstrap.py"
    if not script.exists():
        warn(f"SessionStart: auto-bootstrap fallback unavailable; missing {script}")
        _release_lock(repo_root)
        return False
    try:
        subprocess.Popen(
            [sys.executable, str(script), "--repo-root", str(repo_root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        warn(f"SessionStart: auto-bootstrap launch failed: {error}")
        _release_lock(repo_root)
        return False
    return True


def main() -> int:
    """SessionStart hook entry point.

    Reads the hook payload from stdin (may be empty), validates the system,
    injects memory context into the agent, and returns 0 on success.

    Returns:
        int: 0 on success or graceful noop; 1 on error.
    """
    adapter = detect_adapter()
    set_runtime_log_context(adapter.agent_id())

    # Read and discard the stdin payload -- SessionStart does not consume it,
    # but we parse it here so malformed JSON surfaces as a visible warning rather
    # than a silent truncation error later.
    payload_text = sys.stdin.read().strip()
    if payload_text:
        try:
            json.loads(payload_text)
        except json.JSONDecodeError as error:
            warn(f"SessionStart ignored invalid JSON stdin: {error}")

    home = Path.home()
    refresh_state = home / ".agent" / "state" / "shared_asset_refresh_state.json"
    bootstrap_helper = home / ".agent" / "shared-repo-memory" / "bootstrap-repo.py"
    repo_root = current_repo_root(Path.cwd())
    append_hook_trace("SessionStart", "started", repo_root=repo_root)

    # Feature flag check -- silently exit when the user has not opted in.
    if not is_memory_configured(home):
        append_hook_trace(
            "SessionStart",
            "skipped",
            repo_root=repo_root,
            details={"reason": "shared_repo_memory_disabled"},
        )
        # No output when disabled -- just exit 0 silently so the agent starts normally.
        return 0

    # Repo guard -- the system only operates inside git repos.
    if repo_root is None:
        append_hook_trace(
            "SessionStart",
            "noop",
            repo_root=None,
            details={"reason": "not_in_git_repo"},
        )
        # No output when not in a repo -- just exit 0 silently.
        return 0

    # Verify that all required installed assets are present before proceeding.
    required = [
        bootstrap_helper,
        home / ".agent" / "shared-repo-memory" / "post-turn-notify.py",
        home / ".agent" / "shared-repo-memory" / "pre-commit-memory-guard.py",
        home / ".agent" / "shared-repo-memory" / "rebuild-summary.py",
        home / ".agent" / "shared-repo-memory" / "build-catchup.py",
        home / ".agent" / "shared-repo-memory" / "promote-adr.py",
        home / ".agent" / "shared-repo-memory" / "publish-checkpoint.py",
        refresh_state,
    ]
    missing = [str(path) for path in required if not path.exists()]

    # Skills may be installed under Claude or Codex skill paths; require at least one.
    for skill in ("memory-writer", "memory-checkpointer", "adr-promoter"):
        claude_path = home / ".claude" / "skills" / skill
        codex_path = home / ".codex" / "skills" / skill
        if not claude_path.exists() and not codex_path.exists():
            missing.append(f"{claude_path} or {codex_path}")
    if missing:
        append_hook_trace(
            "SessionStart",
            "error",
            repo_root=repo_root,
            details={"reason": "missing_required_paths", "missing_paths": missing},
        )
        for item in missing:
            warn(f"SessionStart missing required path: {item}")
            emit_session_response(
                "agentmemory setup incomplete: required paths are missing. Re-run ./install.sh.",
            )
        return 1

    # Validate repo wiring; bootstrap any missing structure automatically.
    bootstrapped_repo = False
    issues = repo_wiring_issues(repo_root)
    if issues:
        append_hook_trace(
            "SessionStart",
            "bootstrapping",
            repo_root=repo_root,
            details={"wiring_issues": issues},
        )
        info_message = "SessionStart detected incomplete repo wiring; bootstrapping agentmemory layout."
        warn(info_message)
        if not run_repo_bootstrap(bootstrap_helper, repo_root):
            append_hook_trace(
                "SessionStart",
                "error",
                repo_root=repo_root,
                details={"reason": "repo_bootstrap_failed"},
            )
            emit_session_response(
                "agentmemory bootstrap failed. Check ~/.agent/state/shared-repo-memory-hook-trace.jsonl.",
            )
            return 1
        bootstrapped_repo = True
        # Confirm bootstrap repaired all issues before proceeding.
        issues = repo_wiring_issues(repo_root)
        if issues:
            append_hook_trace(
                "SessionStart",
                "error",
                repo_root=repo_root,
                details={
                    "reason": "repo_wiring_incomplete_after_bootstrap",
                    "missing_paths": issues,
                },
            )
            for item in issues:
                warn(f"SessionStart missing required path: {item}")
            emit_session_response(
                "agentmemory wiring incomplete after bootstrap. Check the hook trace log.",
            )
            return 1

    refresh_data = load_json(refresh_state, {})
    last_refresh = refresh_data.get("last_successful_refresh_at", "unknown")
    append_hook_trace(
        "SessionStart",
        "success",
        repo_root=repo_root,
        details={
            "bootstrapped_repo": bootstrapped_repo,
            "last_successful_refresh_at": last_refresh,
        },
    )
    memory_context = load_memory_context(repo_root)
    daily_dir = repo_root / ".agents" / "memory" / "daily"
    has_shards = any(daily_dir.glob("*/events/*.md")) if daily_dir.is_dir() else False
    suffix = " Repo wiring was bootstrapped this session." if bootstrapped_repo else ""
    warn(
        "SessionStart OK: installed assets, refresh state, and repo wiring are reachable for agentmemory. "
        f"Last shared-asset refresh: {last_refresh}.{suffix}"
    )
    if memory_context and has_shards:
        memory_text: str = memory_context
        status_msg: str = f"agentmemory loaded. Last refresh: {last_refresh}.{suffix}"
    else:
        # No event shard history yet. Spawn a current-runtime subagent when the
        # runtime exposes a supported non-interactive bootstrap command so the
        # seed pass runs in an isolated context without polluting this session.
        spawned = _spawn_subagent_bootstrap(repo_root)
        if spawned:
            bg_note = (
                "Memory bootstrap subagent is running in the background. "
                "Shards will appear in .agents/memory/daily/ shortly. Proceed normally."
            )
        else:
            bg_note = (
                "INSTRUCTION: This repository has no event shard history yet. "
                "Invoke /memory-bootstrap to seed it from existing commits and docs."
            )
        if memory_context:
            memory_text = memory_context + "\n\n" + bg_note
            status_msg = (
                f"agentmemory loaded (ADRs present, no event history). "
                f"Last refresh: {last_refresh}.{suffix}"
            )
        else:
            memory_text = bg_note
            status_msg = (
                f"agentmemory wired but empty. Last refresh: {last_refresh}.{suffix}"
            )

    emit_session_response(status_msg, additional_context=memory_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "SessionStart"))
