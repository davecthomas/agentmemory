#!/usr/bin/env python3
"""Create an ADR and rebuild the index.

Two input modes:

* ``--from-note NOTES_FILE --entry N`` promotes the N-th entry (1-based) of a
  decision-note file. Its Decision, Why, Alternatives, and Scope lines seed
  the ADR sections and the entry is cited under Sources.
* ``--title ... --context ... --decision ...`` writes the ADR from explicit
  text. ``--alternatives``, ``--consequences``, and repeatable ``--source``
  are optional.

``--supersedes ADR-NNNN`` (repeatable) records the relationship both ways:
the new ADR lists what it replaces, and each replaced ADR is marked
``superseded`` with ``superseded_by`` set and ``must_read`` false, so it
leaves the session context.

``--reindex`` only rebuilds ``INDEX.md`` from the ADR files on disk.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import (
    ADR_DIR,
    NOTES_DIR,
    list_adrs,
    log,
    parse_frontmatter,
    read_text,
    render_frontmatter,
    repo_root,
    safe_main,
    slugify,
    stage,
    today,
    write_text,
)


def next_id(root: Path) -> str:
    """Return the next unused ADR identifier.

    Args:
        root: Repository root.

    Returns:
        str: ``ADR-NNNN``.
    """
    highest: int = 0
    for path in (root / ADR_DIR).glob("ADR-*.md"):
        match = re.match(r"ADR-(\d+)", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"ADR-{highest + 1:04d}"


def render_adr(
    *,
    adr_id: str,
    title: str,
    context: str,
    decision: str,
    alternatives: str = "",
    consequences: str = "",
    sources: list[str] | None = None,
    tags: str = "",
    must_read: bool = True,
    date: str | None = None,
    status: str = "accepted",
    supersedes: str = "",
    superseded_by: str = "",
) -> str:
    """Render an ADR document in the v0.5 format.

    Args:
        adr_id: ``ADR-NNNN``.
        title: One-line title.
        context: Context section text.
        decision: Decision section text.
        alternatives: Alternatives section text.
        consequences: Consequences section text.
        sources: Lines for the Sources section.
        tags: Comma-separated tags.
        must_read: Inject the Decision at session start when True.
        date: ISO date; today when omitted.
        status: ``accepted`` or ``superseded``.
        supersedes: Comma-separated ids this ADR replaces.
        superseded_by: Id of the ADR that replaced this one.

    Returns:
        str: Full Markdown document.
    """
    meta: dict[str, Any] = {
        "id": adr_id,
        "title": title,
        "status": status,
        "date": date or today(),
        "tags": tags,
        "must_read": must_read,
        "supersedes": supersedes,
        "superseded_by": superseded_by,
    }
    body: list[str] = [f"# {adr_id}: {title}", ""]
    for heading, text in (
        ("Context", context),
        ("Decision", decision),
        ("Alternatives", alternatives or "None recorded."),
        ("Consequences", consequences or "None recorded."),
    ):
        body += [f"## {heading}", "", text.strip(), ""]
    body += ["## Sources", ""]
    body += [f"- {s}" for s in (sources or [])] or ["- None recorded."]
    return render_frontmatter(meta) + "\n\n" + "\n".join(body) + "\n"


def mark_superseded(root: Path, old_id: str, new_id: str) -> Path:
    """Rewrite an ADR's frontmatter as superseded by ``new_id``.

    Args:
        root: Repository root.
        old_id: Id of the ADR being replaced.
        new_id: Id of the replacement.

    Returns:
        Path: The rewritten file.
    """
    matches = list((root / ADR_DIR).glob(f"{old_id}-*.md"))
    if len(matches) != 1:
        raise SystemExit(
            f"--supersedes {old_id}: expected one file, found {len(matches)}"
        )
    path = matches[0]
    meta, body = parse_frontmatter(read_text(path))
    meta["status"] = "superseded"
    meta["superseded_by"] = new_id
    meta["must_read"] = False
    write_text(path, render_frontmatter(meta) + "\n\n" + body)
    return path


def index_rows(root: Path) -> str:
    """Render ``INDEX.md`` from the ADR files on disk.

    Args:
        root: Repository root.

    Returns:
        str: Full index Markdown.
    """
    rows: list[str] = []
    for adr in list_adrs(root):
        meta = adr["meta"]
        must: str = "yes" if meta.get("must_read") is True else "no"
        status: str = str(meta.get("status", "accepted"))
        if meta.get("superseded_by"):
            status += f" (by {meta['superseded_by']})"
        rows.append(
            f"| {meta['id']} | [{meta['title']}]({adr['path'].name}) | {status} "
            f"| {meta.get('date', '')} | {must} |"
        )
    return (
        "# ADR index\n\n| ADR | Title | Status | Date | Must read |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + ("\n" if rows else "")
    )


def refresh_index(root: Path) -> Path:
    """Rewrite ``INDEX.md``.

    Args:
        root: Repository root.

    Returns:
        Path: The index file.
    """
    path: Path = root / ADR_DIR / "INDEX.md"
    write_text(path, index_rows(root))
    return path


def note_entry(root: Path, notes_file: Path, entry: int) -> dict[str, str]:
    """Extract one entry from a decision-note file.

    Args:
        root: Repository root, for the source citation.
        notes_file: The ``notes/YYYY-MM-DD.md`` file.
        entry: 1-based entry number.

    Returns:
        dict[str, str]: Field name to text, plus ``source``.
    """
    text: str = read_text(notes_file)
    blocks: list[str] = re.split(r"(?m)^## ", text)[1:]
    if not 1 <= entry <= len(blocks):
        raise SystemExit(f"{notes_file} has {len(blocks)} entries; asked for {entry}")
    block: str = blocks[entry - 1]
    fields: dict[str, str] = {"header": block.splitlines()[0].strip()}
    for key in ("Decision", "Why", "Alternatives", "Scope", "Commit"):
        match = re.search(rf"^\*\*{key}:\*\*\s*(.+)$", block, re.MULTILINE)
        fields[key.lower()] = match.group(1).strip() if match else ""
    rel: str = notes_file.relative_to(root).as_posix()
    fields["source"] = f"[{rel} entry {entry}](../../../{rel}): {fields['header']}"
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--from-note", default=None, help="notes file path")
    parser.add_argument("--entry", type=int, default=1)
    parser.add_argument("--title", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--alternatives", default="")
    parser.add_argument("--consequences", default="")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--tags", default="")
    parser.add_argument("--no-must-read", action="store_true")
    parser.add_argument("--supersedes", action="append", default=[], metavar="ADR-NNNN")
    parser.add_argument("--no-stage", action="store_true")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("promote-adr: not inside a git repository")
        return 1
    if args.reindex:
        print(refresh_index(root).relative_to(root))
        return 0

    sources: list[str] = list(args.source)
    if args.from_note:
        notes_file = Path(args.from_note)
        if not notes_file.is_absolute():
            notes_file = root / notes_file
        if not notes_file.is_file() and (root / NOTES_DIR / notes_file.name).is_file():
            notes_file = root / NOTES_DIR / notes_file.name
        fields = note_entry(root, notes_file, args.entry)
        title = args.title or fields["decision"]
        context = args.context or fields["why"]
        decision = args.decision or fields["decision"]
        alternatives = args.alternatives or fields["alternatives"]
        if fields["scope"]:
            sources.append(f"Scope: {fields['scope']}")
        if fields["commit"]:
            sources.append(f"Commit {fields['commit']}")
        sources.append(fields["source"])
    else:
        title, context, decision, alternatives = (
            args.title,
            args.context,
            args.decision,
            args.alternatives,
        )
    if not (title and context and decision):
        parser.error("--title, --context and --decision are required (or --from-note)")

    adr_id: str = next_id(root)
    path: Path = root / ADR_DIR / f"{adr_id}-{slugify(title)}.md"
    write_text(
        path,
        render_adr(
            adr_id=adr_id,
            title=title,
            context=context,
            decision=decision,
            alternatives=alternatives,
            consequences=args.consequences,
            sources=sources,
            tags=args.tags,
            must_read=not args.no_must_read,
            supersedes=", ".join(args.supersedes),
        ),
    )
    retired: list[Path] = [
        mark_superseded(root, old, adr_id) for old in args.supersedes
    ]
    index: Path = refresh_index(root)
    if not args.no_stage:
        stage(root, [path, index, *retired])
    print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "promote-adr"))
