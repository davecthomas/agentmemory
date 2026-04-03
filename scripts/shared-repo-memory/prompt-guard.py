#!/usr/bin/env python3
"""prompt-guard.py -- Pre-turn hook for the shared repo-memory system.

Fires before every user turn.  Its sole job is to detect when a session is
running in a wired repo that has no event shards yet and inject a one-time
bootstrap suggestion so the agent proactively offers to seed memory.

Performance design
------------------
This hook runs on EVERY user prompt, so latency matters.  The fast-exit
strategy keeps the common case (shards already exist, session already seen)
as cheap as possible:

  1. Parse stdin (unavoidable).
  2. Load the tiny session-state JSON (~microseconds).
  3. If session_id is already marked "done" in state -> exit immediately.
     No subprocess, no filesystem traversal, no glob.
  4. Walk up from cwd in pure Python to find the memory root (no git subprocess).
  5. If wiring is absent -> exit.  Mark session done so step 3 fires next time.
  6. Glob for shards (short-circuits on first match via any()).
  7. If shards found -> mark session done, exit.
  8. Only if shards absent: inject nudge, mark session done.

After the FIRST prompt in any session where shards already exist, every
subsequent prompt costs: stdin read + tiny JSON load + dict lookup + exit.

Session-state format
--------------------
~/.agent/state/prompt-guard-sessions.json stores:
  { "<session_id>": "<ISO-8601 timestamp>" }
Entries older than SESSION_TTL_DAYS are pruned on each write.

Supported hook events:
  UserPromptSubmit  -- Claude Code (fires on every user prompt submission)
  BeforeAgent       -- Gemini CLI (fires after user submission, before planning)

Install location after ./install.sh:
  ~/.agent/shared-repo-memory/prompt-guard.py
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

from common import append_hook_trace, utc_now, utc_timestamp

# Path to the per-session state file.
_STATE_FILE: Path = Path.home() / ".agent" / "state" / "prompt-guard-sessions.json"

# Session records older than this are pruned on each write.
_SESSION_TTL_DAYS: int = 7

_NUDGE_TEXT: str = (
    "IMPORTANT: This repository has shared memory wiring but no event shards yet. "
    "Before proceeding with the user's request, offer to run the `news` skill to "
    "seed initial shared memory from the repo's existing design docs and commit "
    "history. Say something like: 'I notice this repo has no shared memory yet — "
    "want me to bootstrap it from the existing history before we start?' "
    "Do not proceed silently without offering this."
)


def _load_sessions() -> dict[str, str]:
    """Read the session-state file, returning an empty dict on any error.

    Returns:
        dict[str, str]: Mapping of session_id to ISO-8601 timestamp.
    """
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sessions(sessions: dict[str, str]) -> None:
    """Write session state, pruning entries older than SESSION_TTL_DAYS.

    Args:
        sessions: Current session_id -> timestamp mapping to persist.
    """
    cutoff: str = utc_timestamp(utc_now() - timedelta(days=_SESSION_TTL_DAYS))
    pruned: dict[str, str] = {k: v for k, v in sessions.items() if v >= cutoff}
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(pruned, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _find_memory_root(start: str) -> Path | None:
    """Walk up from start looking for .agents/memory/adr/INDEX.md.

    Pure Python directory walk -- no git subprocess.  Checks at most 10
    parent levels before giving up.

    Args:
        start: Absolute path to start searching from (typically cwd).

    Returns:
        Path | None: Directory containing .agents/memory/adr/INDEX.md, or None.
    """
    current: Path = Path(start).resolve() if start else Path.cwd()
    for _ in range(10):
        if (current / ".agents" / "memory" / "adr" / "INDEX.md").exists():
            return current
        parent: Path = current.parent
        if parent == current:
            break
        current = parent
    return None


def _has_any_shards(repo_root: Path) -> bool:
    """Return True if any event shard .md files exist under .agents/memory/daily/.

    Uses any() so the glob short-circuits on the first match.

    Args:
        repo_root: Root of the repository.

    Returns:
        bool: True when at least one shard file is present.
    """
    daily_dir: Path = repo_root / ".agents" / "memory" / "daily"
    if not daily_dir.is_dir():
        return False
    return any(daily_dir.glob("*/events/*.md"))


def main() -> int:
    """Entry point: fast-exit when possible, nudge when memory is empty.

    Returns:
        int: Always 0 -- this hook never blocks the turn.
    """
    payload_text: str = sys.stdin.read()
    try:
        payload: dict[str, object] = (
            json.loads(payload_text) if payload_text.strip() else {}
        )
    except json.JSONDecodeError:
        payload = {}

    session_id: str = str(payload.get("session_id", payload.get("sessionId", "")))
    hook_event: str = str(
        payload.get("hook_event_name", payload.get("hookEventName", ""))
    )
    cwd: str = str(payload.get("cwd", ""))

    # --- Fast exit: session already processed ---
    # Load state once; if this session is already marked done, exit immediately
    # without touching the filesystem or spawning any subprocess.
    sessions: dict[str, str] = _load_sessions()
    if session_id and session_id in sessions:
        return 0

    # --- Find repo root (pure Python, no subprocess) ---
    repo_root: Path | None = _find_memory_root(cwd)
    if repo_root is None:
        # Not in a wired repo.  Mark session done to skip this check next time.
        if session_id:
            sessions[session_id] = utc_timestamp()
            _save_sessions(sessions)
        return 0

    # --- Check for existing shards ---
    if _has_any_shards(repo_root):
        # Memory exists.  Mark session done so we never glob again this session.
        if session_id:
            sessions[session_id] = utc_timestamp()
            _save_sessions(sessions)
        return 0

    # --- Inject bootstrap nudge (empty-memory repo) ---
    if session_id:
        sessions[session_id] = utc_timestamp()
        _save_sessions(sessions)

    response: dict[str, object] = {
        "hookSpecificOutput": {
            "hookEventName": hook_event or "UserPromptSubmit",
            "additionalContext": _NUDGE_TEXT,
        }
    }
    print(json.dumps(response, sort_keys=True))

    append_hook_trace(
        "PromptGuard",
        "nudge_injected",
        repo_root=repo_root,
        details={"session_id": session_id, "hook_event": hook_event},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
