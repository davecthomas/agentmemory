#!/usr/bin/env python3
"""post-compact.py -- PostCompact hook for the shared repo-memory system.

Fires after Claude Code compacts (summarises) the context window.  Compaction
discards the full transcript, including the memory context injected by
SessionStart.  Without this hook the agent loses awareness of ADRs and recent
summaries for the remainder of the session.

This script re-injects the same memory context that SessionStart provides:
ADR index + the three most recent daily summaries.

Supported hook events:
  PostCompact -- Claude Code only.  Gemini CLI's PreCompress is advisory-only
                 and fires before compression, so re-injection after compaction
                 is not possible on Gemini CLI.

Install location after ./install.sh:
  ~/.agent/shared-repo-memory/post-compact.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common import append_hook_trace, safe_main, try_repo_root, warn


def _load_memory_context(repo_root: Path) -> str:
    """Load the ADR index and recent daily summaries as a memory context block.

    Re-uses the same bounded read path as session-start.py:
      1. ADR index
      2. Up to 3 most recent daily summary files

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        str: Combined memory context text, or empty string when nothing is available.
    """
    sections: list[str] = []

    # ADR index.
    adr_index: Path = repo_root / ".agents" / "memory" / "adr" / "INDEX.md"
    if adr_index.exists():
        try:
            sections.append("### Architecture Decision Records\n")
            sections.append(adr_index.read_text(encoding="utf-8").strip())
        except OSError:
            pass

    # Most recent daily summaries (newest first, max 3).
    daily_dir: Path = repo_root / ".agents" / "memory" / "daily"
    if daily_dir.is_dir():
        summary_paths: list[Path] = sorted(
            daily_dir.glob("*/summary.md"), reverse=True
        )[:3]
        for summary_path in summary_paths:
            try:
                date_label: str = summary_path.parent.name
                sections.append(f"\n### Memory: {date_label}\n")
                sections.append(summary_path.read_text(encoding="utf-8").strip())
            except OSError:
                pass

    return "\n".join(sections).strip()


def main() -> int:
    """Entry point: re-inject memory context after context compaction.

    Returns:
        int: Always 0 -- this hook never blocks.
    """
    payload_text: str = sys.stdin.read()
    try:
        payload: dict[str, object] = (
            json.loads(payload_text) if payload_text.strip() else {}
        )
    except json.JSONDecodeError:
        payload = {}

    cwd: str = str(payload.get("cwd", ""))
    repo_root = try_repo_root(cwd or None)
    if repo_root is None:
        return 0  # not in a git repo

    memory_context: str = _load_memory_context(repo_root)
    if not memory_context:
        return 0  # nothing to re-inject

    warn("PostCompact: re-injecting shared repo memory context after compaction.")

    response: dict[str, object] = {
        "hookSpecificOutput": {
            "hookEventName": "PostCompact",
            "additionalContext": (
                "Context was compacted. Re-injecting shared repo memory:\n\n"
                + memory_context
            ),
        }
    }
    print(json.dumps(response, sort_keys=True))

    append_hook_trace(
        "PostCompact",
        "context_reinjected",
        repo_root=repo_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "PostCompact"))
