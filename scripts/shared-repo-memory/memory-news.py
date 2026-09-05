#!/usr/bin/env python3
"""Print a bounded, newest-first digest of recent decision memory.

Backs the ``news`` skill: the local catch-up, recent note entries with
candidates flagged, the newest ADRs, and recent code commits that memory
does not mention. Deterministic; no LLM.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (
    LOCAL_DIR,
    MEMORY_DIR,
    git,
    is_opted_in,
    list_adrs,
    list_notes,
    log,
    read_text,
    repo_root,
    safe_main,
    section,
)

MAX_NOTE_ENTRIES: int = 8
MAX_ADRS: int = 5
MAX_COMMITS: int = 12


def note_entries(root: Path, days: int) -> list[str]:
    """Render recent note entries, newest first.

    Args:
        root: Repository root.
        days: Window in days.

    Returns:
        list[str]: One line per entry.
    """
    lines: list[str] = []
    for note in list_notes(root, days):
        for block in reversed(re.split(r"(?m)^## ", read_text(note))[1:]):
            header = block.splitlines()[0].strip()
            decision = re.search(r"\*\*Decision:\*\*\s*(.+)", block)
            flag = (
                " _(candidate, unreviewed)_" if "**Candidate:** true" in block else ""
            )
            lines.append(
                f"- {header}: {decision.group(1).strip() if decision else '(no decision line)'}{flag}"
            )
    return lines[:MAX_NOTE_ENTRIES]


def news(root: Path, days: int) -> str:
    """Build the digest.

    Args:
        root: Repository root.
        days: Window for notes.

    Returns:
        str: Markdown.
    """
    if not is_opted_in(root):
        return "agentmemory: not opted in. Run `/agentmemory init` first.\n"
    out: list[str] = ["# Repo news", ""]
    catchup = read_text(root / LOCAL_DIR / "catchup.md").strip()
    if catchup:
        out += ["## Since this machine last looked", "", catchup, ""]
    notes = note_entries(root, days)
    if notes:
        out += [f"## Decisions noted in the last {days} days", "", *notes, ""]
    adrs = list(reversed(list_adrs(root)))[:MAX_ADRS]
    if adrs:
        out += ["## Newest ADRs", ""]
        for adr in adrs:
            meta = adr["meta"]
            status = meta.get("status", "accepted")
            out.append(
                f"- {meta['id']} ({meta.get('date', '')}, {status}): {meta['title']} — "
                f"{' '.join(section(adr['body'], 'Decision').split()[:40])}…"
            )
        out.append("")
    commits = git(
        [
            "log",
            f"--max-count={MAX_COMMITS}",
            "--format=%h %ad %s",
            "--date=short",
            "--",
            ".",
            f":(exclude){MEMORY_DIR}",
        ],
        root,
    )
    if commits:
        out += [
            "## Recent code commits",
            "",
            *(f"- {c}" for c in commits.splitlines()),
            "",
        ]
    if len(out) == 2:
        out.append(
            "No decision memory yet. Run `/memory-bootstrap` to seed it from docs and history."
        )
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-news: not inside a git repository")
        return 1
    print(news(root, args.days), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-news"))
