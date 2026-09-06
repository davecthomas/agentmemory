#!/usr/bin/env python3
"""Answer "what do we know about X?" from repo memory.

Searches ADRs, decision notes, and ``docs/*.md`` for the query terms, and
when a term is a tracked path also shows its recent git history. Results
within each section are ranked by how many distinct terms they match, with
title hits weighted above body hits. Output is bounded Markdown meant to be
read by an agent mid-session; ``--json`` emits the same data for tooling.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import (
    NOTES_DIR,
    git,
    list_adrs,
    list_notes,
    log,
    note_date,
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


def _rank(title: str, body: str, terms: list[str]) -> int:
    """Score a document: 2 per term in the title, 1 per term in the body.

    Args:
        title: Title text.
        body: Body text.
        terms: Lowercased query terms.

    Returns:
        int: Score; 0 means no match.
    """
    lt, lb = title.lower(), body.lower()
    return sum((2 if t in lt else 0) + (1 if t in lb else 0) for t in terms)


def _snippet(text: str) -> str:
    words: list[str] = text.split()
    return " ".join(words[:SNIPPET_WORDS]) + (
        " …" if len(words) > SNIPPET_WORDS else ""
    )


def collect(root: Path, query: list[str]) -> dict[str, Any]:
    """Gather ranked matches for a query.

    Args:
        root: Repository root.
        query: Query words or paths.

    Returns:
        dict[str, Any]: ``adrs``, ``notes``, ``docs``, ``history`` lists.
    """
    terms: list[str] = _terms(query)
    result: dict[str, Any] = {
        "query": query,
        "adrs": [],
        "notes": [],
        "docs": [],
        "history": [],
    }
    if not terms:
        return result

    for adr in list_adrs(root):
        meta, body = adr["meta"], adr["body"]
        score = _rank(f"{meta['title']} {meta.get('tags', '')}", body, terms)
        if score:
            result["adrs"].append(
                {
                    "id": meta["id"],
                    "title": meta["title"],
                    "status": str(meta.get("status", "accepted")),
                    "path": adr["path"].relative_to(root).as_posix(),
                    "decision": _snippet(section(body, "Decision")),
                    "score": score,
                }
            )
    result["adrs"].sort(key=lambda a: (-a["score"], a["id"]), reverse=False)
    result["adrs"] = sorted(result["adrs"], key=lambda a: (-a["score"], a["id"]))[
        :MAX_ADRS
    ]

    for note in list_notes(root):
        for block in re.split(r"(?m)^## ", read_text(note))[1:]:
            decision = re.search(r"\*\*Decision:\*\*\s*(.+)", block)
            why = re.search(r"\*\*Why:\*\*\s*(.+)", block)
            score = _rank(decision.group(1) if decision else "", block, terms)
            if score:
                result["notes"].append(
                    {
                        "date": note_date(note),
                        "header": block.splitlines()[0].strip(),
                        "decision": decision.group(1).strip() if decision else "",
                        "why": _snippet(why.group(1)) if why else "",
                        "score": score,
                    }
                )
    result["notes"] = sorted(
        result["notes"], key=lambda n: (-n["score"], n["date"]), reverse=False
    )
    result["notes"] = sorted(result["notes"], key=lambda n: (-n["score"], n["date"]))[
        :MAX_NOTES
    ]

    for doc in sorted((root / "docs").glob("**/*.md")):
        text = read_text(doc)
        matched = [
            line.strip()
            for line in text.splitlines()
            if _hit(line, terms) and line.strip()
        ][:MAX_DOC_LINES]
        if matched:
            result["docs"].append(
                {
                    "path": doc.relative_to(root).as_posix(),
                    "lines": matched,
                    "score": _rank(doc.name, text, terms),
                }
            )
    result["docs"] = sorted(result["docs"], key=lambda d: (-d["score"], d["path"]))[
        :MAX_ADRS
    ]

    for raw in query:
        if (root / raw).exists() and not raw.startswith(NOTES_DIR):
            history = git(
                [
                    "log",
                    f"--max-count={MAX_COMMITS}",
                    "--format=%h %ad %s",
                    "--date=short",
                    "--",
                    raw,
                ],
                root,
            )
            if history:
                result["history"].append({"path": raw, "commits": history.splitlines()})
    return result


def query_memory(root: Path, query: list[str]) -> str:
    """Build the Markdown answer for a query.

    Args:
        root: Repository root.
        query: Query words or paths.

    Returns:
        str: Markdown; says so when nothing matched.
    """
    if not _terms(query):
        return "Give me a topic or a path to look up."
    data = collect(root, query)
    out: list[str] = [f"# Memory for: {' '.join(query)}", ""]
    if data["adrs"]:
        out += ["## ADRs", ""]
        out += [
            f"- **{a['id']}** [{a['title']}]({a['path']}) ({a['status']}): {a['decision']}"
            for a in data["adrs"]
        ]
        out.append("")
    if data["notes"]:
        out += ["## Decision notes", ""]
        out += [
            f"- {n['date']} ({n['header']}): {n['decision']} — {n['why']}"
            for n in data["notes"]
        ]
        out.append("")

    if data["docs"]:
        out += ["## Design docs", ""]
        out += [f"- `{d['path']}`: " + " / ".join(d["lines"]) for d in data["docs"]]
        out.append("")
    for h in data["history"]:
        out += [f"## Recent commits touching `{h['path']}`", ""]
        out += [f"- {c}" for c in h["commits"]]
        out.append("")

    if len(out) == 2:
        out.append("Nothing in ADRs, notes, or docs mentions this yet.")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-query: not inside a git repository")
        return 1
    if args.json:
        print(json.dumps(collect(root, args.query), indent=2))
        return 0
    print(query_memory(root, args.query), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-query"))
