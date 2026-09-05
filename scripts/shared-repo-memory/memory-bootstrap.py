#!/usr/bin/env python3
"""Mine a repository's docs and commit history for decision candidates.

Backs the ``memory-bootstrap`` skill. Prints a ranked, bounded list of
candidates with their source so the agent (or a human) chooses which three
to seven become ADRs through ``promote-adr.py``. Deterministic; no LLM.

Signals, in scoring order:

* Markdown sections under ``docs/``, ``README.md``, ``AGENTS.md``, and
  ``CLAUDE.md`` whose heading contains a decision word (decision, principle,
  architecture, design, why, rationale, convention, policy)
* Commit bodies that explain a reason (``because``, ``so that``,
  ``instead of``, ``rather than``, ``trade-off``) or carry a ``Decision:``
  line, weighted by how many files the commit touched
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from common import MEMORY_DIR, git, is_opted_in, log, read_text, repo_root, safe_main

DOC_FILES: tuple[str, ...] = ("README.md", "AGENTS.md", "CLAUDE.md")
HEADING_WORDS: re.Pattern[str] = re.compile(
    r"decision|principle|architecture|design|why|rationale|convention|policy|"
    r"trade-?off|constraint|invariant",
    re.IGNORECASE,
)
REASON_WORDS: re.Pattern[str] = re.compile(
    r"\bbecause\b|\bso that\b|\binstead of\b|\brather than\b|\btrade-?off\b|"
    r"^Decision:",
    re.IGNORECASE | re.MULTILINE,
)
MAX_COMMITS: int = 300
SNIPPET_WORDS: int = 45


@dataclass
class Candidate:
    score: float
    title: str
    source: str
    snippet: str
    kind: str  # "doc" or "commit"


def _snippet(text: str) -> str:
    words = " ".join(text.split()).split()
    return " ".join(words[:SNIPPET_WORDS]) + ("…" if len(words) > SNIPPET_WORDS else "")


def doc_candidates(root: Path) -> list[Candidate]:
    """Find decision-bearing sections in the repo's Markdown docs.

    Args:
        root: Repository root.

    Returns:
        list[Candidate]: One per matching heading.
    """
    paths: list[Path] = [root / f for f in DOC_FILES if (root / f).is_file()]
    paths += sorted((root / "docs").glob("**/*.md"))
    found: list[Candidate] = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel.startswith(MEMORY_DIR):
            continue
        text = read_text(path)
        for match in re.finditer(r"(?m)^(#{1,4})\s+(.+?)\s*$", text):
            heading = match.group(2)
            if not HEADING_WORDS.search(heading):
                continue
            start = match.end()
            nxt = re.search(r"(?m)^#{1,4}\s", text[start:])
            body = text[start : start + nxt.start()] if nxt else text[start:]
            body = body.strip()
            if len(body.split()) < 12:
                continue
            depth = len(match.group(1))
            score = 3.0 - 0.3 * depth + min(len(body.split()), 300) / 300
            found.append(
                Candidate(
                    score=round(score, 2),
                    title=heading,
                    source=f"{rel} § {heading}",
                    snippet=_snippet(body),
                    kind="doc",
                )
            )
    return found


def commit_candidates(root: Path, limit: int) -> list[Candidate]:
    """Find commits whose body explains a reason.

    Args:
        root: Repository root.
        limit: Commits to scan, newest first.

    Returns:
        list[Candidate]: One per qualifying commit.
    """
    raw = git(
        [
            "log",
            f"--max-count={limit}",
            "--format=%x1e%h%x1f%ad%x1f%s%x1f%b",
            "--date=short",
            "--shortstat",
        ],
        root,
    )
    found: list[Candidate] = []
    # git() strips the output and \x1e counts as whitespace, so the first
    # record's separator is gone; split and skip empties instead of dropping [0].
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        sha, date, subject, body = parts[0], parts[1], parts[2], parts[3]
        files = re.search(r"(\d+) files? changed", body)
        body = re.sub(r"\n?\s*\d+ files? changed[^\n]*\n?$", "", body)
        # Drop trailers (ai-model: ..., Co-Authored-By: ...) but keep Decision: lines.
        body = re.sub(r"(?m)^(?!Decision:)[A-Za-z][A-Za-z-]*: \S.*$", "", body).strip()
        if not REASON_WORDS.search(body):
            continue
        touched = int(files.group(1)) if files else 1
        decision = re.search(r"(?im)^Decision:\s*(.+)$", body)
        score = 1.0 + min(touched, 20) / 20 + (1.0 if decision else 0.0)
        found.append(
            Candidate(
                score=round(score, 2),
                title=decision.group(1).strip() if decision else subject,
                source=f"commit {sha} ({date})",
                snippet=_snippet(body),
                kind="commit",
            )
        )
    return found


def render(candidates: list[Candidate], limit: int) -> str:
    """Render the ranked list.

    Args:
        candidates: All candidates.
        limit: Maximum to show.

    Returns:
        str: Markdown.
    """
    # Docs outscore commits by construction, so take the best of each kind
    # before merging; otherwise a doc-heavy repo never shows a commit.
    per_kind: int = max(1, (limit + 1) // 2)
    docs = sorted(
        (c for c in candidates if c.kind == "doc"), key=lambda c: (-c.score, c.source)
    )
    commits = sorted(
        (c for c in candidates if c.kind == "commit"),
        key=lambda c: (-c.score, c.source),
    )
    ranked = sorted(
        docs[:per_kind] + commits[:per_kind], key=lambda c: (-c.score, c.source)
    )
    if len(ranked) < limit:
        rest = [c for c in docs[per_kind:] + commits[per_kind:]]
        ranked += sorted(rest, key=lambda c: (-c.score, c.source))[
            : limit - len(ranked)
        ]
    if not ranked:
        return "No decision candidates found in docs or commit bodies.\n"
    out = [
        "# Decision candidates",
        "",
        "Pick three to seven that still govern the code and promote each with "
        "`promote-adr.py --title … --context … --decision … --alternatives … "
        "--consequences … --source <source>`.",
        "",
    ]
    for n, c in enumerate(ranked, start=1):
        out += [
            f"## {n}. {c.title}",
            "",
            f"- Source: {c.source}",
            f"- Kind: {c.kind}; score {c.score}",
            f"- {c.snippet}",
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--limit", type=int, default=15, help="candidates to show")
    parser.add_argument(
        "--commits", type=int, default=MAX_COMMITS, help="commits to scan"
    )
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-bootstrap: not inside a git repository")
        return 1
    if not is_opted_in(root):
        log("memory-bootstrap: repo has not opted in; run /agentmemory init first")
        return 1
    print(
        render(
            doc_candidates(root) + commit_candidates(root, args.commits), args.limit
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-bootstrap"))
