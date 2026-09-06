#!/usr/bin/env python3
"""Stop hook: ask once per session for a decision note when work went unrecorded.

Runs when the agent finishes a turn. If files outside ``.agents/memory``
changed during the session and today's note file has not grown since
session start, it returns ``decision: block`` once, with a reason that
tells the agent to record a note with the ``memory-note`` skill or to say
that no decision was made. It never fires twice in one session, never
fires when ``stop_hook_active`` is set (the agent is already answering a
block), and never spawns anything. Cost: one ``git status`` and a stat.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from common import (
    LOCAL_DIR,
    MEMORY_DIR,
    NOTES_DIR,
    dump_json,
    git,
    is_opted_in,
    load_json,
    read_stdin_json,
    repo_root,
    safe_main,
    stamp,
    today,
)

REASON: str = (
    "agentmemory: this session changed files in the repository but no decision "
    "note was recorded. If you made a non-obvious choice (a trade-off, a rejected "
    "alternative, a constraint you discovered), record it now with the "
    "`memory-note` skill. If there was no such choice, reply that no decision "
    "note is needed and finish."
)
MAX_SESSIONS: int = 20


def notes_size(root: Path) -> int:
    """Size in bytes of today's note file, 0 when absent.

    Args:
        root: Repository root.

    Returns:
        int: Byte size.
    """
    path = root / NOTES_DIR / f"{today()}.md"
    return path.stat().st_size if path.is_file() else 0


def record_session(root: Path, session_id: str) -> None:
    """Remember the note size at session start so the Stop hook can compare.

    Called by ``session-start.py``. Keeps the newest ``MAX_SESSIONS`` entries.

    Args:
        root: Repository root.
        session_id: Claude Code session id from the hook payload.
    """
    if not session_id:
        return
    path = root / LOCAL_DIR / "state.json"
    state = load_json(path, {})
    if not isinstance(state, dict):
        state = {}
    sessions: dict[str, Any] = state.setdefault("sessions", {})
    sessions[session_id] = {
        "started": stamp(),
        "notes_size": notes_size(root),
        "nudged": False,
    }
    for old in sorted(sessions, key=lambda k: sessions[k].get("started", ""))[
        :-MAX_SESSIONS
    ]:
        del sessions[old]
    dump_json(path, state)


def work_happened(root: Path) -> bool:
    """True when the working tree has changes outside ``.agents/memory``.

    Args:
        root: Repository root.

    Returns:
        bool: Whether repo files changed.
    """
    # .gitignore is excluded because bootstrap --init edits it; that is wiring,
    # not work, and would otherwise nudge on the first stop after opting in.
    status = git(
        [
            "status",
            "--porcelain",
            "--",
            ".",
            f":(exclude){MEMORY_DIR}",
            ":(exclude).gitignore",
        ],
        root,
    )
    return bool(status.strip())


def should_nudge(root: Path, payload: dict[str, Any]) -> bool:
    """Decide whether to block this stop with the note reminder.

    Args:
        root: Repository root.
        payload: Stop hook payload.

    Returns:
        bool: True when the reminder should fire; the session is marked nudged.
    """
    if payload.get("stop_hook_active"):
        return False
    session_id = str(payload.get("session_id", ""))
    path = root / LOCAL_DIR / "state.json"
    state = load_json(path, {})
    sessions = state.get("sessions", {}) if isinstance(state, dict) else {}
    info = sessions.get(session_id)
    if not isinstance(info, dict) or info.get("nudged"):
        return False
    if notes_size(root) > int(info.get("notes_size", 0)):
        return False
    if not work_happened(root):
        return False
    info["nudged"] = True
    info["nudged_at"] = stamp()
    dump_json(path, state)
    return True


def main() -> int:
    if os.environ.get("AGENTMEMORY_DISABLED"):
        return 0
    payload = read_stdin_json()
    root = repo_root(payload.get("cwd") or None)
    if root is None or not is_opted_in(root):
        return 0
    if should_nudge(root, payload):
        print(json.dumps({"decision": "block", "reason": REASON}))
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "turn-nudge"))
