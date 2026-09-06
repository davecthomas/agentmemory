#!/usr/bin/env python3
"""Append one decision note to ``.agents/memory/notes/YYYY-MM-DD.md``.

Notes are the capture unit for decision memory: three lines written at the
moment a non-obvious choice is made, by the agent or by a human.

The note is written and left unstaged. ``memory-commit.py`` gathers the
repository's outstanding memory into its own commit, so decisions land in the
same pull request as the code without being swept into an unrelated commit.
``--stage`` restores the old behaviour for anyone who wants the note carried
by their next commit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    NOTES_DIR,
    author_slug,
    current_branch,
    log,
    read_text,
    repo_root,
    safe_main,
    stage,
    stamp,
    today,
    write_text,
)


def render_entry(
    *,
    decision: str,
    why: str,
    author: str,
    branch: str,
    alternatives: str = "",
    scope: list[str] | None = None,
    commit: str = "",
    source: str = "",
    when: str | None = None,
) -> str:
    """Render one note entry.

    Args:
        decision: What was decided, one sentence.
        why: The reason, one to three sentences.
        author: Author slug.
        branch: Branch name.
        alternatives: Rejected options, optional.
        scope: Paths the decision applies to, optional.
        commit: Short sha when the entry came from a commit.
        source: Provenance when a hook wrote the entry, e.g. ``commit-capture``.
        when: Timestamp override; now when omitted.

    Returns:
        str: Markdown entry ending in a blank line.
    """
    lines: list[str] = [
        f"## {when or stamp()} · {author} · {branch}",
        "",
        f"**Decision:** {decision.strip()}",
        f"**Why:** {why.strip()}",
    ]
    if alternatives.strip():
        lines.append(f"**Alternatives:** {alternatives.strip()}")
    if scope:
        lines.append(f"**Scope:** {', '.join(scope)}")
    if commit:
        lines.append(f"**Commit:** {commit}")
    if source:
        lines.append(f"**Source:** {source}")
    return "\n".join(lines) + "\n\n"


def append_note(
    root: Path, entry: str, *, date: str | None = None, author: str | None = None
) -> Path:
    """Append an entry to the day's note file, creating it with a header.

    The file is ``YYYY-MM-DD--<author>.md`` when an author is given, so two
    people writing notes on the same day never edit the same file and never
    merge-conflict. Plain ``YYYY-MM-DD.md`` files from before remain valid.

    Args:
        root: Repository root.
        entry: Rendered entry from ``render_entry``.
        date: ``YYYY-MM-DD`` override; today when omitted.
        author: Author slug for the per-author filename.

    Returns:
        Path: The note file.
    """
    day: str = date or today()
    name: str = f"{day}--{author}.md" if author else f"{day}.md"
    path: Path = root / NOTES_DIR / name
    existing: str = read_text(path)
    if not existing:
        existing = f"# Decision notes {day}\n\n"
    elif not existing.endswith("\n\n"):
        existing = existing.rstrip("\n") + "\n\n"
    write_text(path, existing + entry)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--why", required=True)
    parser.add_argument("--alternatives", default="")
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument(
        "--stage", action="store_true", help="stage the note; memory-commit does this"
    )
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-note: not inside a git repository")
        return 1
    author: str = author_slug(root)
    entry: str = render_entry(
        decision=args.decision,
        why=args.why,
        author=author,
        branch=current_branch(root),
        alternatives=args.alternatives,
        scope=args.scope,
    )
    path: Path = append_note(root, entry, author=author)
    if args.stage:
        stage(root, [path])
    log(f"decision note recorded in {path.relative_to(root)}", wrote=True)
    print(str(path.relative_to(root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-note"))
