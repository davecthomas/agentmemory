#!/usr/bin/env python3
"""Answer "what do we know about X?" from repo memory.

Searches ADRs, decision notes, and ``docs/*.md`` for the query terms, and
when a term is a tracked path also shows its recent git history. Output is
bounded Markdown meant to be read by an agent mid-session.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (
    NOTES_DIR,
    git,
    list_adrs,
    list_notes,
    log,
    read_text,
    repo_root,
    safe_main,
    section,
)

MAX_ADRS: int = 8
MAX_NOTES: int = 8
MAX_DOC_LINES: int = 3
MAX_COMMITS: int = 15
SNIPPET_WORDS: int = 60


def _terms(query: list[str]) -> list[str]:
    return [t.lower() for t in " ".join(query).split() if len(t) > 1]


def _hit(text: str, terms: list[str]) -> bool:
    low: str = text.lower()
    return any(t in low for t in terms)


def _snippet(text: str) -> str:
    words: list[str] = text.split()
    return " ".join(words[:SNIPPET_WORDS]) + (
        " …" if len(words) > SNIPPET_WORDS else ""
    )


def query_memory(root: Path, query: list[str]) -> str:
    """Build the Markdown answer for a query.

    Args:
        root: Repository root.
        query: Query words or paths.

    Returns:
        str: Markdown; says so when nothing matched.
    """
    terms: list[str] = _terms(query)
    if not terms:
        return "Give me a topic or a path to look up."
    out: list[str] = [f"# Memory for: {' '.join(query)}", ""]

    adr_lines: list[str] = []
    for adr in reversed(list_adrs(root)):
        meta, body = adr["meta"], adr["body"]
        if _hit(f"{meta['title']} {meta.get('tags', '')} {body}", terms):
            rel: str = adr["path"].relative_to(root).as_posix()
            status: str = str(meta.get("status", "accepted"))
            adr_lines.append(
                f"- **{meta['id']}** [{meta['title']}]({rel}) ({status}): "
                f"{_snippet(section(body, 'Decision'))}"
            )
    if adr_lines:
        out += ["## ADRs", "", *adr_lines[:MAX_ADRS], ""]

    note_lines: list[str] = []
    for note in list_notes(root):
        for block in re.split(r"(?m)^## ", read_text(note))[1:]:
            if _hit(block, terms):
                header: str = block.splitlines()[0].strip()
                decision = re.search(r"\*\*Decision:\*\*\s*(.+)", block)
                why = re.search(r"\*\*Why:\*\*\s*(.+)", block)
                note_lines.append(
                    f"- {note.stem} ({header}): "
                    f"{decision.group(1) if decision else ''} "
                    f"— {_snippet(why.group(1)) if why else ''}"
                )
    if note_lines:
        out += ["## Decision notes", "", *note_lines[:MAX_NOTES], ""]

    doc_lines: list[str] = []
    for doc in sorted((root / "docs").glob("**/*.md")):
        matched: list[str] = [
            line.strip()
            for line in read_text(doc).splitlines()
            if _hit(line, terms) and line.strip()
        ][:MAX_DOC_LINES]
        if matched:
            rel = doc.relative_to(root).as_posix()
            doc_lines.append(f"- `{rel}`: " + " / ".join(matched))
    if doc_lines:
        out += ["## Design docs", "", *doc_lines[:MAX_ADRS], ""]

    for raw in query:
        if (root / raw).exists() and not raw.startswith(NOTES_DIR):
            history: str = git(
                [
                    "log",
                    f"--max-count={MAX_COMMITS}",
                    "--format=- %h %ad %s",
                    "--date=short",
                    "--",
                    raw,
                ],
                root,
            )
            if history:
                out += [f"## Recent commits touching `{raw}`", "", history, ""]

    if len(out) == 2:
        out.append("Nothing in ADRs, notes, or docs mentions this yet.")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-query: not inside a git repository")
        return 1
    print(query_memory(root, args.query), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-query"))
