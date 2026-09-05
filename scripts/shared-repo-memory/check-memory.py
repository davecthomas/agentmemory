#!/usr/bin/env python3
"""Structural checks on a repo's decision memory. Exit 1 on any failure.

Runs from the generated ``pre-commit`` hook in every opted-in repo, and from
CI here, so broken memory cannot be committed:

* every ``INDEX.md`` row names an existing ADR file, and every ADR file has
  a row
* every ADR has frontmatter with ``id``, ``title``, ``status``, ``date``,
  ``must_read`` and the five required sections
* every relative Markdown link under ``.agents/memory/`` resolves
* every note file is named ``YYYY-MM-DD.md`` and every entry has Decision
  and Why lines
* the session-start context fits ``context_budget_words`` without omitting
  a must-read ADR
* no accepted ADR still carries the ``None recorded.`` placeholder in its
  Alternatives section; a decision with no considered alternative is a wish
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

PLACEHOLDER: str = "None recorded."

REQUIRED_META: tuple[str, ...] = ("id", "title", "status", "date", "must_read")
LINK: re.Pattern[str] = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


def check_adrs(root: Path) -> list[str]:
    problems: list[str] = []
    adr_dir: Path = root / common.ADR_DIR
    files: set[str] = {p.name for p in adr_dir.glob("ADR-*.md")}
    index_text: str = common.read_text(adr_dir / "INDEX.md")
    indexed: set[str] = set(re.findall(r"\]\((ADR-[^)]+\.md)\)", index_text))
    for name in sorted(files - indexed):
        problems.append(f"{common.ADR_DIR}/{name}: missing from INDEX.md")
    for name in sorted(indexed - files):
        problems.append(f"INDEX.md: row points at missing {name}")
    for adr in common.list_adrs(root):
        rel: str = adr["path"].relative_to(root).as_posix()
        meta, body = adr["meta"], adr["body"]
        raw_meta, _ = common.parse_frontmatter(common.read_text(adr["path"]))
        for key in REQUIRED_META:
            if key not in raw_meta:
                problems.append(f"{rel}: frontmatter lacks {key}")
        if not isinstance(raw_meta.get("must_read"), bool):
            problems.append(f"{rel}: must_read must be true or false")
        expected: str = adr["path"].name.split("-", 2)
        expected_id: str = f"{expected[0]}-{expected[1]}"
        if raw_meta.get("id") != expected_id:
            problems.append(f"{rel}: id {raw_meta.get('id')!r} does not match filename")
        for heading in common.ADR_SECTIONS:
            if not common.section(body, heading):
                problems.append(f"{rel}: empty or missing '## {heading}'")
        if meta.get("must_read") is True and not common.section(body, "Decision"):
            problems.append(f"{rel}: must-read ADR has no Decision to inject")
        if (
            meta.get("status") == "accepted"
            and common.section(body, "Alternatives").strip() == PLACEHOLDER
        ):
            problems.append(f"{rel}: accepted ADR has placeholder Alternatives")
    return problems


def check_links(root: Path) -> list[str]:
    problems: list[str] = []
    for md in sorted((root / common.MEMORY_DIR).rglob("*.md")):
        if common.LOCAL_DIR in md.as_posix():
            continue
        for target in LINK.findall(common.read_text(md)):
            if target.startswith(("http://", "https://")):
                continue
            if not (md.parent / target).exists():
                rel = md.relative_to(root).as_posix()
                problems.append(f"{rel}: link to missing {target}")
    return problems


def check_notes(root: Path) -> list[str]:
    problems: list[str] = []
    for note in sorted((root / common.NOTES_DIR).glob("*.md")):
        rel: str = note.relative_to(root).as_posix()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", note.name):
            problems.append(f"{rel}: note files must be named YYYY-MM-DD.md")
            continue
        blocks: list[str] = re.split(r"(?m)^## ", common.read_text(note))[1:]
        if not blocks:
            problems.append(f"{rel}: no entries")
        for number, block in enumerate(blocks, start=1):
            for key in ("Decision", "Why"):
                if not re.search(rf"^\*\*{key}:\*\*\s*\S", block, re.MULTILINE):
                    problems.append(f"{rel} entry {number}: missing **{key}:** line")
    return problems


def check_budget(root: Path) -> list[str]:
    config = common.load_config(root)
    context: str = common.build_memory_context(root, config)
    problems: list[str] = []
    budget: int = int(config["context_budget_words"])
    words: int = common.word_count(context)
    if words > budget * 1.1:
        problems.append(f"context is {words} words; budget {budget}")
    omitted = re.search(r"_Omitted to stay under \d+ words: (.+?)\. Use", context)
    if omitted and "ADR-" in omitted.group(1):
        problems.append(
            "must-read ADRs do not fit the budget: "
            f"{omitted.group(1)}. Raise context_budget_words or set must_read false."
        )
    return problems


def run(root: Path) -> list[str]:
    if not common.is_opted_in(root):
        return []
    return check_adrs(root) + check_links(root) + check_notes(root) + check_budget(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()
    root = common.repo_root(args.repo_root)
    if root is None:
        print("check_memory: not inside a git repository", file=sys.stderr)
        return 1
    problems: list[str] = run(root)
    for problem in problems:
        print(f"memory check: {problem}", file=sys.stderr)
    adr_count, note_count = common.memory_counts(root)
    print(
        f"memory check: {adr_count} ADRs, {note_count} note files, "
        f"{len(problems)} problem{'s' if len(problems) != 1 else ''}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
