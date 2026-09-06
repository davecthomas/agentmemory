#!/usr/bin/env python3
"""Stage the repository's uncommitted decision memory and draft its commit message.

Memory is written by hooks and skills but never committed automatically
(ADR-0004). This gathers whatever is outstanding under ``.agents/memory/``,
excluding the gitignored ``local/`` cache, stages it, and prints a message
describing the decisions it carries.

The message names the decisions and the ADRs, because that is what a reviewer
needs. It does not carry setup instructions: those live in the README and in
the ``AGENTS.md`` block that ``bootstrap-repo.py --init`` writes. The one
exception is a repository's first memory commit, where ``.agents/memory/``
appears for the first time and a teammate deserves a pointer.

``--commit`` performs the commit. Without it the files are staged and the
message goes to stdout, so a caller can route it through its own commit flow.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from common import (
    ADR_DIR,
    LOCAL_DIR,
    MEMORY_DIR,
    NOTES_DIR,
    current_branch,
    git,
    is_opted_in,
    log,
    note_date,
    parse_frontmatter,
    read_text,
    repo_root,
    safe_main,
    section,
)

MAX_LISTED: int = 12
POINTER: str = (
    "Captured by agentmemory. The convention lives in the repository's "
    'AGENTS.md under "Decision memory".'
)
FIRST_COMMIT_POINTER: str = (
    "This is this repository's first decision-memory commit.\n"
    "\n"
    ".agents/memory/ holds the decisions behind the code: notes/ as they are\n"
    "made, adr/ once they prove durable. Agents read it at the start of every\n"
    "session, so a decision recorded here reaches your teammates' agents too.\n"
    "\n"
    "Nothing happens in a clone until someone installs the tooling, and the\n"
    "files stay readable Markdown either way. Setup, configuration, and removal\n"
    'are documented in AGENTS.md under "Decision memory".'
)


def outstanding(root: Path) -> list[str]:
    """Return uncommitted memory paths: staged, unstaged, and untracked.

    Args:
        root: Repository root.

    Returns:
        list[str]: Repo-relative paths, excluding the gitignored local cache.
    """
    raw: str = git(
        ["status", "--porcelain", "--untracked-files=all", "--", MEMORY_DIR],
        root,
        strip=False,
    )
    paths: list[str] = []
    for line in raw.splitlines():
        path = line[3:].strip()
        # A rename reports "old -> new"; the new path is what gets committed.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and not path.startswith(f"{LOCAL_DIR}/"):
            paths.append(path)
    return sorted(set(paths))


def new_decisions(root: Path, paths: list[str]) -> list[tuple[str, str]]:
    """Read decision lines from note files that are not yet committed.

    Only entries absent from ``HEAD`` are reported, so re-running after a
    partial commit does not repeat what already landed.

    Args:
        root: Repository root.
        paths: Outstanding memory paths.

    Returns:
        list[tuple[str, str]]: ``(date, decision)`` pairs, oldest first.
    """
    found: list[tuple[str, str]] = []
    for path in paths:
        if not path.startswith(f"{NOTES_DIR}/"):
            continue
        committed: str = git(["show", f"HEAD:{path}"], root)
        for block in re.split(r"(?m)^## ", read_text(root / path))[1:]:
            match = re.search(r"^\*\*Decision:\*\*\s*(.+)$", block, re.MULTILINE)
            if not match:
                continue
            if committed and match.group(1).strip() in committed:
                continue
            found.append((note_date(Path(path)), match.group(1).strip()))
    return found


def new_adrs(root: Path, paths: list[str]) -> list[tuple[str, str, str]]:
    """Read id, title, and status from outstanding ADR files.

    Args:
        root: Repository root.
        paths: Outstanding memory paths.

    Returns:
        list[tuple[str, str, str]]: ``(id, title, status)``, sorted by id.
    """
    found: list[tuple[str, str, str]] = []
    for path in paths:
        name = Path(path).name
        if not path.startswith(f"{ADR_DIR}/") or not name.startswith("ADR-"):
            continue
        meta, body = parse_frontmatter(read_text(root / path))
        parts = Path(path).stem.split("-", 2)
        found.append(
            (
                str(meta.get("id") or f"{parts[0]}-{parts[1]}"),
                str(meta.get("title") or (section(body, "Decision")[:60] or name)),
                str(meta.get("status", "accepted")),
            )
        )
    return sorted(found)


def is_first_memory_commit(root: Path) -> bool:
    """True when no ADR or note has ever been committed in this repository.

    The empty ``INDEX.md`` that ``bootstrap-repo.py --init`` creates does not
    count: it is wiring, and treating it as memory would suppress the pointer
    on the very commit that introduces the first real decision.

    Args:
        root: Repository root.

    Returns:
        bool: Whether this would be the first.
    """
    return not git(
        [
            "log",
            "--max-count=1",
            "--format=%h",
            "--",
            f"{ADR_DIR}/ADR-*.md",
            f"{NOTES_DIR}/*.md",
        ],
        root,
    )


def build_message(
    root: Path,
    paths: list[str],
    *,
    branch: str,
    first: bool,
) -> str:
    """Compose the commit message for the outstanding memory.

    Args:
        root: Repository root.
        paths: Outstanding memory paths.
        branch: Current branch, used in the subject.
        first: Whether this is the repository's first memory commit.

    Returns:
        str: Full commit message.
    """
    decisions = new_decisions(root, paths)
    adrs = new_adrs(root, paths)
    counts: list[str] = []
    if decisions:
        counts.append(f"{len(decisions)} decision{'s' if len(decisions) != 1 else ''}")
    if adrs:
        counts.append(f"{len(adrs)} ADR{'s' if len(adrs) != 1 else ''}")
    what: str = " and ".join(counts) if counts else f"{len(paths)} memory files"
    lines: list[str] = [f"memory: {what} from {branch}", ""]
    if decisions:
        lines.append("Decisions recorded:")
        lines += [f"- {date}: {text}" for date, text in decisions[:MAX_LISTED]]
        if len(decisions) > MAX_LISTED:
            lines.append(f"- ... and {len(decisions) - MAX_LISTED} more")
        lines.append("")
    if adrs:
        lines.append("ADRs:")
        lines += [
            f"- {i} ({status}): {title}" for i, title, status in adrs[:MAX_LISTED]
        ]
        lines.append("")
    lines.append(FIRST_COMMIT_POINTER if first else POINTER)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--commit", action="store_true", help="commit, do not just stage"
    )
    parser.add_argument(
        "--no-stage", action="store_true", help="print the message only"
    )
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-commit: not inside a git repository")
        return 1
    if not is_opted_in(root):
        log("memory-commit: repository has not opted in; run /agentmemory init first")
        return 1
    paths: list[str] = outstanding(root)
    if not paths:
        log("memory-commit: no uncommitted decision memory")
        return 0
    message: str = build_message(
        root,
        paths,
        branch=current_branch(root),
        first=is_first_memory_commit(root),
    )
    if not args.no_stage:
        git(["add", "--", *paths], root)
    if args.commit:
        result = subprocess.run(
            ["git", "commit", "-F", "-", "--", *paths],
            cwd=str(root),
            input=message,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"memory-commit: commit failed: {result.stderr.strip()[:300]}")
            return 1
        log(f"memory-commit: committed {len(paths)} memory files")
        return 0
    print(message, end="")
    for path in paths:
        print(path, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-commit"))
