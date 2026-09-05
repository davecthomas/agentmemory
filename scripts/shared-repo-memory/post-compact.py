#!/usr/bin/env python3
"""PostCompact hook: re-inject decision memory after context compaction.

Uses the same bounded block as SessionStart so a compacted session keeps
the repo's decisions in context.
"""

from __future__ import annotations

import json
import os

from common import (
    build_memory_context,
    is_opted_in,
    read_stdin_json,
    repo_root,
    safe_main,
)


def main() -> int:
    if os.environ.get("AGENTMEMORY_DISABLED"):
        return 0
    payload = read_stdin_json()
    root = repo_root(payload.get("cwd") or None)
    if root is None or not is_opted_in(root):
        return 0
    context: str = build_memory_context(root)
    if not context:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostCompact",
                    "additionalContext": (
                        "Context was compacted. Re-injecting agentmemory:\n\n" + context
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "post-compact"))
