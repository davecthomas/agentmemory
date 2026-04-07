#!/usr/bin/env python3
"""prompt-guard.py -- Pre-turn hook for the shared repo-memory system.

Fires before every user turn.  Its sole job is to detect when a session is
running in a wired repo that has no event shards yet and inject a one-time
recovery suggestion so the agent proactively offers to run the
`memory-bootstrap` skill before proceeding.

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

from adapters import detect_adapter_from_hook_event
from common import append_hook_trace, info, safe_main, utc_now, utc_timestamp, warn

# Path to the per-session state file.
_STATE_FILE: Path = Path.home() / ".agent" / "state" / "prompt-guard-sessions.json"

# Session records older than this are pruned on each write.
_SESSION_TTL_DAYS: int = 7

_NUDGE_TEXT: str = (
    "INSTRUCTION: This repository has shared memory wiring but no event shards yet. "
    "Before proceeding, proactively offer to run the `memory-bootstrap` skill so "
    "the operator can seed shared memory history from recent commits and design docs."
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


def _walk_to_memory_root(start: Path) -> Path | None:
    """Walk up from start looking for .agents/memory/adr/INDEX.md.

    Pure Python directory walk -- no git subprocess.  Checks at most 10
    parent levels before giving up.

    Args:
        start: Absolute path to begin the upward search from.

    Returns:
        Path | None: Directory containing .agents/memory/adr/INDEX.md, or None.
    """
    current: Path = start.resolve()
    for _ in range(10):
        if (current / ".agents" / "memory" / "adr" / "INDEX.md").exists():
            return current
        parent: Path = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_memory_root(payload_cwd: str) -> Path | None:
    """Find the repo memory root, preferring the process cwd over the payload cwd.

    Claude Code launches hook subprocesses with the project directory as their
    working directory, so Path.cwd() is always correct.  The payload's cwd
    field is used only as a fallback in case the process cwd is not inside a
    wired repo (e.g. when running tests or in unusual environments).

    Args:
        payload_cwd: The cwd field from the hook payload, may be empty.

    Returns:
        Path | None: Repo root with memory wiring, or None if not found.
    """
    # Primary: process cwd -- reliable because Claude Code sets it to the project dir.
    result: Path | None = _walk_to_memory_root(Path.cwd())
    if result is not None:
        return result
    # Fallback: payload cwd field.
    if payload_cwd:
        return _walk_to_memory_root(Path(payload_cwd))
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
        warn("PromptGuard: invalid JSON payload on stdin")
        payload = {}

    # Detect adapter and normalize the payload through it.
    hook_event_raw: str = str(
        payload.get("hook_event_name", payload.get("hookEventName", ""))
    )
    adapter = detect_adapter_from_hook_event(hook_event_raw)
    req = adapter.normalize_hook_request(payload)
    info(
        f"PromptGuard: fired ({adapter.agent_id()}, event={req.hook_event or 'unknown'}, session={req.session_id or 'none'})"
    )

    # --- Fast exit: session already processed ---
    # Load state once; if this session is already marked done, exit immediately
    # without touching the filesystem or spawning any subprocess.
    sessions: dict[str, str] = _load_sessions()
    if req.session_id and req.session_id in sessions:
        info("PromptGuard: fast exit -- session already seen")
        append_hook_trace(
            "PromptGuard",
            "fast_exit",
            details={"reason": "session_already_seen", "session_id": req.session_id},
        )
        return 0

    # --- Find repo root (pure Python, no subprocess) ---
    repo_root: Path | None = _find_memory_root(req.cwd)
    if repo_root is None:
        # Not in a wired repo.  Mark session done to skip this check next time.
        if req.session_id:
            sessions[req.session_id] = utc_timestamp()
            _save_sessions(sessions)
        info(f"PromptGuard: noop -- no wired repo found from cwd={req.cwd or 'empty'}")
        append_hook_trace(
            "PromptGuard",
            "noop",
            details={"reason": "no_wired_repo", "cwd": req.cwd},
        )
        return 0

    # --- Check for existing shards ---
    if _has_any_shards(repo_root):
        # Memory exists.  Mark session done so we never glob again this session.
        if req.session_id:
            sessions[req.session_id] = utc_timestamp()
            _save_sessions(sessions)
        info(f"PromptGuard: noop -- shards already exist in {repo_root}")
        append_hook_trace(
            "PromptGuard",
            "noop",
            repo_root=repo_root,
            details={"reason": "shards_exist", "session_id": req.session_id},
        )
        return 0

    # --- Inject a one-time recovery nudge for empty-memory repos ---
    # Mark the session done immediately so the documented nudge fires at most
    # once per session rather than hijacking every prompt.
    if req.session_id:
        sessions[req.session_id] = utc_timestamp()
        _save_sessions(sessions)

    # Emit hookSpecificOutput directly for context injection -- the same shape
    # used by post-compact.py.  render_hook_response() adds a top-level "status"
    # field that pre-turn hooks did not previously include, so we avoid it here
    # until a dedicated context-injection renderer is added to the adapter protocol.
    hook_event: str = req.hook_event or "UserPromptSubmit"
    response: dict[str, object] = {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "additionalContext": _NUDGE_TEXT,
        }
    }
    print(json.dumps(response, sort_keys=True))

    info(f"PromptGuard: injected memory-bootstrap nudge for session {req.session_id}")
    append_hook_trace(
        "PromptGuard",
        "nudge_injected",
        repo_root=repo_root,
        details={"session_id": req.session_id, "hook_event": hook_event},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "PromptGuard"))
