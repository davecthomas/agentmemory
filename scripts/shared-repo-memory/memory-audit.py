#!/usr/bin/env python3
"""Report ADRs whose governed code has changed a lot since the decision.

An ADR names the paths it governs in its ``scope`` field. Nothing checked
whether that code still matches the decision, so an ADR could stay must-read
and keep steering sessions long after the code was rewritten around it.

This is advisory and never fails anything: churn is a reason to look, not
proof that a decision is wrong. ``news`` shows the top entries; run this
directly for the whole list.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import git, is_opted_in, list_adrs, log, repo_root, safe_main

MAX_REPORTED: int = 5
MIN_COMMITS: int = 5


def scope_paths(adr: dict[str, Any]) -> list[str]:
    """Paths an ADR governs, from its ``scope`` field.

    Args:
        adr: An entry from ``list_adrs``.

    Returns:
        list[str]: Repo-relative paths, empty when the ADR names none.
    """
    raw = str(adr["meta"].get("scope", ""))
    return [p.strip() for p in raw.replace(",", " ").split() if p.strip()]


def churn_since(root: Path, paths: list[str], adr_path: Path) -> int:
    """Count commits touching ``paths`` since the ADR itself landed.

    Measured from the commit that added the ADR rather than from its ``date``
    field: a bare date is parsed inconsistently by ``git log --since``, and the
    commit is what the decision was actually true of. An ADR not yet committed
    has nothing to compare against and reports no churn.

    Args:
        root: Repository root.
        paths: Repo-relative paths the ADR governs.
        adr_path: The ADR file.

    Returns:
        int: Commit count.
    """
    if not paths:
        return 0
    rel = adr_path.relative_to(root).as_posix()
    added = git(["log", "--diff-filter=A", "--format=%H", "--", rel], root).split()
    if not added:
        return 0
    out = git(["log", "--format=%h", f"{added[-1]}..HEAD", "--", *paths], root)
    return len(out.split())


def stale_adrs(
    root: Path, minimum: int = MIN_COMMITS
) -> list[tuple[int, str, str, str]]:
    """ADRs whose scope has seen heavy change since the decision, busiest first.

    Args:
        root: Repository root.
        minimum: Commits required before an ADR is worth reporting.

    Returns:
        list[tuple[int, str, str, str]]: ``(commits, id, title, scope)``.
    """
    found: list[tuple[int, str, str, str]] = []
    for adr in list_adrs(root):
        meta = adr["meta"]
        if meta.get("status") == "superseded":
            continue
        paths = scope_paths(adr)
        commits = churn_since(root, paths, adr["path"])
        if commits >= minimum:
            found.append(
                (commits, str(meta["id"]), str(meta["title"]), ", ".join(paths))
            )
    return sorted(found, key=lambda f: (-f[0], f[1]))


def render(found: list[tuple[int, str, str, str]], limit: int) -> str:
    """Render the report.

    Args:
        found: Output of ``stale_adrs``.
        limit: Maximum entries.

    Returns:
        str: Markdown, or a line saying nothing needs review.
    """
    if not found:
        return "No ADR's scope has changed enough since the decision to need review.\n"
    lines = ["# ADRs worth re-reading", ""]
    for commits, adr_id, title, scope in found[:limit]:
        lines.append(
            f"- {adr_id} ({title}) governs `{scope}`, which has changed in "
            f"{commits} commits since. Confirm it still holds, or supersede it."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--limit", type=int, default=MAX_REPORTED)
    parser.add_argument("--min-commits", type=int, default=MIN_COMMITS)
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-audit: not inside a git repository")
        return 1
    if not is_opted_in(root):
        log("memory-audit: repository has not opted in")
        return 1
    print(render(stale_adrs(root, args.min_commits), args.limit), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-audit"))
