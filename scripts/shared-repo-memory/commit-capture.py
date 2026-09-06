#!/usr/bin/env python3
"""post-commit hook: turn a decision-bearing commit into a decision note.

A commit qualifies when its message body has a ``Decision:`` line, explains a
reason (``because``, ``so that``, ``instead of``, ``rather than``, trade-off),
or touches a path matching ``decision_surfaces`` in
``.agents/memory/config.json`` (default ``docs/**``). The commit body is
copied verbatim as the *why*; no LLM is involved. The note is left unstaged
for ``memory-commit.py`` to gather, so it never rides silently into the next
code commit. Commits that only touch ``.agents/memory/`` are skipped so
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
_SCAFFOLD: re.Pattern[str] = re.compile(r"^(?:=+|-+|Summary:|Actions:|Note: .*)\s*$")
MAX_SCOPE: int = 10


def strip_trailers(body: str) -> str:
    """Drop the trailing ``Key: value`` block from a commit body.

    Args:
        body: Commit body without the subject.

    Returns:
        str: Body with trailers removed and whitespace collapsed.
    """
    cleaned: str = "\n".join(
        line for line in body.splitlines() if not _SCAFFOLD.match(line.strip())
    )
    paragraphs: list[str] = [
        p for p in re.split(r"\n\s*\n", cleaned.strip()) if p.strip()
    ]
    while paragraphs and all(
        _TRAILER.match(line) for line in paragraphs[-1].splitlines()
    ):
        paragraphs.pop()
    # A structured message (Summary paragraph, then Actions bullets) carries its
    # why in the first prose paragraph; keep the bullets out of the note.
    prose: list[str] = [p for p in paragraphs if not p.lstrip().startswith("- ")]
    return " ".join(" ".join(p.split()) for p in (prose or paragraphs))


def strip_branch_prefix(subject: str, branch: str) -> str:
    """Drop a leading ``<branch>: `` from a commit subject.

    Args:
        subject: Commit subject line.
        branch: Current branch name.

    Returns:
        str: Subject without the prefix the commit skill adds.
    """
    prefix: str = f"{branch}: "
    if branch and subject.startswith(prefix):
        return subject[len(prefix) :]
    # Any <type>/<slug>: prefix, so subjects written on another branch or
    # carried through a squash merge are cleaned the same way.
    return re.sub(r"^[a-z]+/[\w.-]+: ", "", subject)


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
    """Write a decision note for one commit when it qualifies.

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
    branch: str = current_branch(root)
    subject: str = strip_branch_prefix(
        git(["log", "-1", "--format=%s", sha], root), branch
    )
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
    author: str = author_slug(root)
    entry: str = note.render_entry(
        decision=explicit or subject,
        why=why or subject,
        author=author,
        branch=branch,
        scope=hits[:MAX_SCOPE],
        commit=short,
        source="commit-capture",
    )
    return note.append_note(root, entry, author=author)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument(
        "--stage", action="store_true", help="stage the note; memory-commit does this"
    )
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("commit-capture: not inside a git repository")
        return 1
    path = capture(root, args.sha)
    if path is None:
        return 0
    if args.stage:
        stage(root, [path])
    log(f"decision note captured from commit into {path.relative_to(root)}", wrote=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "commit-capture"))
