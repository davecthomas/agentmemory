#!/usr/bin/env python3
"""Report agentmemory's state for the current repository.

Backs ``/agentmemory status``: opt-in, wiring gaps, counts, must-read ADRs,
and the size of the block a new session gets.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    CONFIG_FILE,
    build_memory_context,
    is_opted_in,
    list_adrs,
    list_notes,
    load_config,
    load_module,
    log,
    note_date,
    repo_root,
    safe_main,
    word_count,
)

HERE: Path = Path(__file__).resolve().parent
TOKENS_PER_WORD: float = 1.3


def status_report(root: Path, *, with_context: bool = False) -> str:
    """Build the status text.

    Args:
        root: Repository root.
        with_context: Append the injected block itself.

    Returns:
        str: Markdown report.
    """
    if not is_opted_in(root):
        return (
            f"agentmemory: not opted in ({CONFIG_FILE} missing). "
            "Run `/agentmemory init` to opt this repo in.\n"
        )
    session = load_module(HERE / "session-start.py")
    issues: list[str] = session.wiring_issues(root)
    cfg = load_config(root)
    adrs = list_adrs(root)
    must = [a["meta"]["id"] for a in adrs if a["meta"].get("must_read") is True]
    superseded = sum(1 for a in adrs if a["meta"].get("status") == "superseded")
    notes = list_notes(root)
    context = build_memory_context(root, cfg)
    words = word_count(context)
    lines: list[str] = [
        "# agentmemory status",
        "",
        f"- Opted in: yes ({CONFIG_FILE})",
        f"- Wiring: {'complete' if not issues else 'incomplete: ' + ', '.join(issues) + ' (next session start repairs it)'}",
        f"- ADRs: {len(adrs)} ({len(must)} must-read, {superseded} superseded)",
        f"- Note files: {len(notes)}"
        + (f", newest {note_date(notes[0])}" if notes else ""),
        f"- Session context: {words} words ≈ {int(words * TOKENS_PER_WORD)} tokens "
        f"of a {cfg['context_budget_words']}-word budget",
        f"- Decision surfaces: {', '.join(cfg['decision_surfaces'])}",
        f"- Must-read: {', '.join(must) or 'none'}",
    ]
    if with_context:
        lines += ["", "## Injected context", "", context or "(empty)"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--context", action="store_true", help="print the block too")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-status: not inside a git repository")
        return 1
    print(status_report(root, with_context=args.context), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-status"))
