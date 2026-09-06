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
WROTE: str = (
    "agentmemory: {n} decision note{s} {were} recorded this session in {paths}. "
    "Tell the developer in one line what was recorded and where, then finish."
)
MAX_SESSIONS: int = 20


def notes_size(root: Path) -> int:
    """Total size in bytes of today's note files (all authors), 0 when none.

    Args:
        root: Repository root.

    Returns:
        int: Byte size.
    """
    return sum(p.stat().st_size for p in (root / NOTES_DIR).glob(f"{today()}*.md"))


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
        "reported": False,
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
    # .gitignore and .gitattributes are excluded because bootstrap --init edits
    # them; that is wiring, not work, and would otherwise nudge on the first
    # stop after opting in.
    status = git(
        [
            "status",
            "--porcelain",
            "--",
            ".",
            f":(exclude){MEMORY_DIR}",
            ":(exclude).gitignore",
            ":(exclude).gitattributes",
        ],
        root,
    )
    return bool(status.strip())


def notes_written(root: Path, since: int) -> list[Path]:
    """Today's note files that grew since the session started.

    Args:
        root: Repository root.
        since: Total byte size of today's notes at session start.

    Returns:
        list[Path]: The note files, when the total grew.
    """
    files = sorted((root / NOTES_DIR).glob(f"{today()}*.md"))
    return files if sum(f.stat().st_size for f in files) > since else []


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
    # A note may have been written by the post-commit hook rather than by a
    # skill, in which case nothing has told the developer. Say so once.
    session = str(payload.get("session_id", ""))
    state = load_json(root / LOCAL_DIR / "state.json", {})
    info = (state.get("sessions", {}) if isinstance(state, dict) else {}).get(session)
    if isinstance(info, dict) and not info.get("reported"):
        written = notes_written(root, int(info.get("notes_size", 0)))
        if written:
            info["reported"] = True
            dump_json(root / LOCAL_DIR / "state.json", state)
            n = len(written)
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": WROTE.format(
                            n=n,
                            s="" if n == 1 else "s",
                            were="was" if n == 1 else "were",
                            paths=", ".join(str(p.relative_to(root)) for p in written),
                        ),
                    }
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "turn-nudge"))
