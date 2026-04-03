#!/usr/bin/env python3
"""build-catchup.py -- Build the local catch-up digest (.codex/local/catchup.md).

The catch-up digest is a concise, always-uncommitted summary of what changed
since the last time this script ran.  It is the first context an agent reads
when resuming work after a git pull, branch switch, or rebase.

This script is called automatically by the git hooks in .githooks/:
  post-checkout, post-merge, post-rewrite

It can also be called manually:
  build-catchup.py --repo-root <path> [--trigger <label>]

Output files (both under .codex/local/, never committed):
  catchup.md       -- human-readable Markdown digest
  sync_state.json  -- watermark used to track what was seen last time

Sections:
  ADR changes          -- links to the 10 most recent ADR files
  Summary changes      -- links to the 2 most recent daily summaries
  Active blockers      -- deduplicated blocker lines from recent summaries
  Next likely steps    -- deduplicated next-step lines from recent summaries
  Referenced shards    -- links to event shards mentioned in recent summaries (max 20)

Usage:
  build-catchup.py --repo-root <path> [--trigger <label>]

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/build-catchup.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    dump_json,
    ensure_dir,
    head_sha,
    load_json,
    relative_link,
    utc_now,
    utc_timestamp,
    write_text,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with repo_root (required) and
            trigger (optional label describing what initiated this rebuild).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--trigger", default="manual")
    return parser.parse_args()


def latest_summaries(repo_root: Path) -> list[Path]:
    """Return the two most recent daily summary.md paths, sorted oldest-first.

    Limiting to two days keeps the catch-up digest focused on the most
    recent activity without growing unboundedly.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        list[Path]: Up to two paths to summary.md files; empty list when none exist.
    """
    daily_root = repo_root / ".agents/memory" / "daily"
    if not daily_root.exists():
        return []
    summaries = sorted(daily_root.glob("*/summary.md"))
    return summaries[-2:]


def adr_files(repo_root: Path) -> list[Path]:
    """Return all ADR-*.md files under .agents/memory/adr/, sorted by name.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        list[Path]: Sorted ADR file paths; empty list when none exist.
    """
    adr_root = repo_root / ".agents/memory" / "adr"
    if not adr_root.exists():
        return []
    return sorted(path for path in adr_root.glob("ADR-*.md"))


def file_hash(path: Path) -> str:
    """Return the SHA-1 hex digest of a file's contents, used as a change watermark.

    Returns an empty string when the file does not exist, so callers can store
    and compare hashes without special-casing absent files.

    Args:
        path: File to hash.

    Returns:
        str: 40-character hex SHA-1 digest, or empty string if path does not exist.
    """
    import hashlib

    if not path.exists():
        return ""
    return hashlib.sha1(path.read_bytes()).hexdigest()


def summary_bullets(path: Path, heading: str) -> list[str]:
    """Extract bullet lines from a named section in a summary.md file.

    Parses the summary by scanning for H2 headings ("## <heading>") and
    collecting all "- " lines until the next heading.

    Args:
        path: Path to a summary.md file.
        heading: Exact heading text to look for (e.g., "Active blockers").

    Returns:
        list[str]: Bullet lines from the matching section; empty list if the
            section is absent or contains no bullet lines.
    """
    current = None
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            continue
        if current == heading and line.startswith("- "):
            lines.append(line)
    return lines


def main() -> int:
    """Entry point: build catchup.md and update sync_state.json.

    Returns:
        int: Always 0 (errors are surfaced via exceptions).
    """
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    local_root = ensure_dir(repo_root / ".codex" / "local")
    catchup_path = local_root / "catchup.md"
    sync_state_path = local_root / "sync_state.json"

    # Load previous sync state so we can compute the catchup window.
    previous = load_json(sync_state_path, {})
    summaries = latest_summaries(repo_root)
    adrs = adr_files(repo_root)

    # Build relative Markdown links to the 10 most recent ADRs.
    adr_changes = [
        f"- {relative_link(catchup_path, path, path.stem)}" for path in adrs[-10:]
    ]

    # Build relative Markdown links to the two most recent daily summaries.
    summary_changes = [
        f"- {summary_path.parent.name}: {relative_link(catchup_path, summary_path, 'summary.md')}"
        for summary_path in summaries
    ]

    # Aggregate blockers, next steps, and shard references from recent summaries.
    blockers: list[str] = []
    next_steps: list[str] = []
    referenced: list[str] = []
    for summary_path in summaries:
        for line in summary_bullets(summary_path, "Active blockers"):
            if line != "- None" and line not in blockers:
                blockers.append(line)
        for line in summary_bullets(summary_path, "Next likely steps"):
            if line != "- None" and line not in next_steps:
                next_steps.append(line)
        # Re-resolve shard links relative to catchup.md rather than summary.md,
        # since the two files are in different directories.
        for line in summary_bullets(summary_path, "Relevant event shards"):
            if line != "- None":
                shard_name = line.removeprefix("- ").split("](", 1)[0].lstrip("[")
                target = summary_path.parent / "events" / f"{shard_name}.md"
                link = f"- {relative_link(catchup_path, target, shard_name)}"
                if link not in referenced:
                    referenced.append(link)

    lines = [
        "# Local catch-up",
        "",
        "## ADR changes",
        "",
        *(adr_changes or ["- None"]),
        "",
        "## Summary changes",
        "",
        *(summary_changes or ["- None"]),
        "",
        "## Active blockers",
        "",
        *(blockers[:10] or ["- None"]),
        "",
        "## Next likely steps",
        "",
        *(next_steps[:10] or ["- None"]),
        "",
        "## Referenced event shards",
        "",
        *(referenced[:20] or ["- None"]),
        "",
    ]
    write_text(catchup_path, "\n".join(lines))

    # Update sync_state.json with the current HEAD and file hashes so the next
    # run can detect what actually changed.
    now = utc_now()
    window_start = previous.get("catchup_window_end") or utc_timestamp(now)
    window_end = utc_timestamp(now)
    latest_summary = summaries[-1] if summaries else None
    sync_state = {
        "last_seen_head": head_sha(repo_root),
        "last_processed_adr_revision": file_hash(
            repo_root / ".agents/memory" / "adr" / "INDEX.md"
        ),
        "last_processed_summary_revision": (
            file_hash(latest_summary) if latest_summary else ""
        ),
        "last_catchup_build_time": window_end,
        "catchup_window_start": window_start,
        "catchup_window_end": window_end,
        "last_trigger": args.trigger,
    }
    dump_json(sync_state_path, sync_state)
    print(f"[shared-repo-memory] catch-up rebuilt via {args.trigger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
