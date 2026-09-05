#!/usr/bin/env python3
"""post-commit hook: turn a decision-bearing commit into a candidate note.

A commit qualifies when its message body has a ``Decision:`` line, explains a
reason (``because``, ``so that``, ``instead of``, ``rather than``, trade-off),
or touches a path matching ``decision_surfaces`` in
``.agents/memory/config.json`` (default ``docs/**``). The commit body is
copied verbatim as the *why*; no LLM is involved. Commits that only touch ``.agents/memory/`` are skipped so
the hook never feeds itself.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (
    MEMORY_DIR,
    REASON_WORDS,
    author_slug,
    current_branch,
    git,
    load_config,
    load_module,
    log,
    matches_surface,
    repo_root,
    safe_main,
    stage,
)

HERE: Path = Path(__file__).resolve().parent
_TRAILER: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z-]*: \S")
MAX_SCOPE: int = 10


def strip_trailers(body: str) -> str:
    """Drop the trailing ``Key: value`` block from a commit body.

    Args:
        body: Commit body without the subject.

    Returns:
        str: Body with trailers removed and whitespace collapsed.
    """
    paragraphs: list[str] = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    while paragraphs and all(
        _TRAILER.match(line) for line in paragraphs[-1].splitlines()
    ):
        paragraphs.pop()
    return " ".join(" ".join(p.split()) for p in paragraphs)


def decision_line(body: str) -> str:
    """Return the text after a ``Decision:`` line in the body, if any.

    Args:
        body: Commit body.

    Returns:
        str: Decision text or ``""``.
    """
    match = re.search(r"^Decision:\s*(.+)$", body, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def capture(root: Path, sha: str = "HEAD") -> Path | None:
    """Write a candidate note for one commit when it qualifies.

    Args:
        root: Repository root.
        sha: Commit to inspect.

    Returns:
        Path | None: The note file written, or None when skipped.
    """
    files: list[str] = git(["show", "--format=", "--name-only", sha], root).splitlines()
    files = [f for f in files if f]
    if not files or all(f.startswith(f"{MEMORY_DIR}/") for f in files):
        return None
    subject: str = git(["log", "-1", "--format=%s", sha], root)
    body: str = git(["log", "-1", "--format=%b", sha], root)
    short: str = git(["rev-parse", "--short", sha], root)
    surfaces: list[str] = list(load_config(root)["decision_surfaces"])
    hits: list[str] = [f for f in files if matches_surface(f, surfaces)]
    explicit: str = decision_line(body)
    why: str = strip_trailers(re.sub(r"^Decision:.*$", "", body, flags=re.M | re.I))
    reasoned: bool = bool(REASON_WORDS.search(why))
    if not explicit and not hits and not reasoned:
        return None
    note = load_module(HERE / "memory-note.py")
    entry: str = note.render_entry(
        decision=explicit or subject,
        why=why or subject,
        author=author_slug(root),
        branch=current_branch(root),
        scope=hits[:MAX_SCOPE],
        commit=short,
        candidate=True,
    )
    return note.append_note(root, entry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--no-stage", action="store_true")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("commit-capture: not inside a git repository")
        return 1
    path = capture(root, args.sha)
    if path is None:
        return 0
    if not args.no_stage:
        stage(root, [path])
    log(f"candidate decision note appended to {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "commit-capture"))
