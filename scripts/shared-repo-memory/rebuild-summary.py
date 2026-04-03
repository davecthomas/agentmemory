#!/usr/bin/env python3
"""rebuild-summary.py -- Regenerate a daily summary from all event shards for a given date.

This script is always called by post-turn-notify.py after a new shard is written.
It can also be called directly to repair or backfill a summary.

The summary is a deterministic read model -- it is always rebuilt from scratch by
reading every shard in .agents/memory/daily/<date>/events/.  Never edit summary.md
directly; it will be overwritten on the next shard write.

Sections produced:
  Snapshot          -- table of event count, top work item, top decision, blockers
  Major work completed -- deduplicated "What changed" excerpts (max 10)
  Why this mattered    -- deduplicated "Why" excerpts (max 10)
  Active blockers      -- lines matching blocker keywords, per branch+thread (max 10)
  Decision candidates  -- shards flagged decision_candidate: true (max 10)
  Next likely steps    -- "Next" lines, deduplicated per thread (max 10)
  Relevant event shards -- relative Markdown links to contributing shards (max 10)

Usage:
  rebuild-summary.py --repo-root <path> [--date YYYY-MM-DD]

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/rebuild-summary.py
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path

from common import (
    excerpt,
    iso_date,
    list_event_files,
    load_event,
    relative_link,
    utc_now,
    write_text,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with repo_root (required) and
            optional date (defaults to today in UTC).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--date")
    return parser.parse_args()


def is_blocker_line(line: str) -> bool:
    """Return True if a shard section line describes a blocker.

    Explicitly excludes "no blockers" and "no blocker" phrasing so that lines
    affirming the absence of blockers are not counted as blockers themselves.

    Args:
        line: A single bullet line from a shard's Why, Evidence, or Next section.

    Returns:
        bool: True if the line contains a blocker keyword and is not a negation.
    """
    lowered = line.lower()
    if "no blockers" in lowered or "no blocker" in lowered:
        return False
    return any(
        token in lowered
        for token in ["blocked", "blocker", "waiting on", "cannot", "can't"]
    )


def first_entry(entries: list[str], default: str) -> str:
    """Return the text of the first entry, stripping any "- " prefix.

    Args:
        entries: List of bullet-prefixed strings.
        default: Fallback when the list is empty.

    Returns:
        str: First entry with "- " stripped, or default when entries is empty.
    """
    if not entries:
        return default
    return entries[0].removeprefix("- ").strip()


def short_event_label(event: dict[str, object]) -> str:
    """Return a short human-readable label for an event shard, used as link text.

    Format: "YYYY-MM-DD HH:MM:SS UTC by <author>"

    Args:
        event: Loaded event dict containing timestamp and author fields.

    Returns:
        str: Short label string.
    """
    timestamp = str(event["timestamp"]).replace("T", " ")
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + " UTC"
    author = str(event.get("author", "unknown"))
    return f"{timestamp} by {author}"


def main() -> int:
    """Entry point: read all shards for the target date and write summary.md.

    Returns:
        int: Always 0 (errors are surfaced via exceptions).
    """
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    day = args.date or iso_date(utc_now())
    day_dir = repo_root / ".agents/memory" / "daily" / day
    summary_path = day_dir / "summary.md"

    # Load and sort all shards for the day by timestamp, then filename for stability.
    events = [load_event(path) for path in list_event_files(day_dir)]
    events.sort(key=lambda item: (item["timestamp"], Path(item["__path"]).name))

    # Accumulators for each summary section.
    work: list[str] = []
    rationale: list[str] = []
    # Keyed by (branch, thread_id) so each active thread contributes at most one blocker line.
    blockers: OrderedDict[str, str] = OrderedDict()
    decision_candidates: list[str] = []
    # Keyed by (branch, thread_id) so each thread contributes only its latest next steps.
    next_steps_by_thread: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
    # Keyed by shard basename to deduplicate references across multiple extractions.
    referenced: OrderedDict[str, str] = OrderedDict()

    for event in events:
        sections = event["__sections"]
        basename = event["__basename"]
        shard_link = relative_link(
            summary_path, event["__path"], short_event_label(event)
        )
        what = sections["What changed"]
        why = sections["Why"]
        evidence = sections["Evidence"]
        next_lines = sections["Next"]

        # Extract a single work item from "What changed".
        if what:
            work_item = excerpt(what, f"Updated repo state in {basename}.")
            bullet = f"- {work_item}"
            if bullet not in work:
                work.append(bullet)
            referenced[basename] = f"- {shard_link}"

        # Extract a single rationale item from "Why" (fall back to evidence).
        why_item = excerpt(why or evidence, "")
        if why_item:
            bullet = f"- {why_item}"
            if bullet not in rationale:
                rationale.append(bullet)
            referenced[basename] = f"- {shard_link}"

        # Scan all three sections for blocker language.
        for line in why + evidence + next_lines:
            if is_blocker_line(line):
                blockers[(event["branch"], event["thread_id"])] = (
                    f"- {line.lstrip('- ').strip()}"
                )
                referenced[basename] = f"- {shard_link}"

        # Record decision candidates with a link for easy promotion later.
        if event["decision_candidate"]:
            text = excerpt(why or what, "Decision candidate")
            decision_candidates.append(f"- {text} ({shard_link})")
            referenced[basename] = f"- {shard_link}"

        # Track next steps per thread; later threads override earlier ones.
        if next_lines:
            next_steps_by_thread[(event["branch"], event["thread_id"])] = [
                f"- {line.lstrip('- ').strip()}" for line in next_lines
            ]
            referenced[basename] = f"- {shard_link}"

    # Flatten per-thread next steps into a deduplicated list.
    next_steps: list[str] = []
    for lines in next_steps_by_thread.values():
        for line in lines:
            if line not in next_steps:
                next_steps.append(line)

    referenced_lines = list(referenced.values())
    snapshot_lines = [
        f"- Captured {len(events)} memory event{'s' if len(events) != 1 else ''}.",
        f"- Main work: {first_entry(work, 'No repo changes recorded.')}",
        f"- Top decision: {first_entry(decision_candidates, 'None.')}",
        f"- Blockers: {first_entry(list(blockers.values()), 'None.')}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Memory events captured | {len(events)} |",
        f"| Repo files changed | {len(work)} |",
        f"| Decision candidates | {len(decision_candidates)} |",
        f"| Active blockers | {len(blockers)} |",
    ]

    # Each section is capped at 10 entries to keep summaries scannable.
    sections = OrderedDict(
        [
            (f"{day} summary", []),
            ("Major work completed", work[:10]),
            ("Why this mattered", rationale[:10]),
            ("Active blockers", list(blockers.values())[:10]),
            ("Decision candidates", decision_candidates[:10]),
            ("Next likely steps", next_steps[:10]),
            ("Relevant event shards", referenced_lines[:10]),
        ]
    )

    lines = [
        f"# {day} summary",
        "",
        "## Snapshot",
        "",
        *snapshot_lines,
        "",
    ]
    for title, entries in list(sections.items())[1:]:
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(entries or ["- None"])
        lines.append("")

    write_text(summary_path, "\n".join(lines).rstrip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
