#!/usr/bin/env python3
"""promote-adr.py -- Promote a decision-candidate event shard into a permanent ADR.

An Architecture Decision Record (ADR) is the durable form of a design decision.
Decision-candidate shards are raw captures; ADRs are curated, indexed, and
committed alongside the code they govern.

Promotion is always explicit -- it never happens automatically as a post-turn
side effect.  Only shards with decision_candidate: true in their frontmatter
are accepted.

What this script does:
  1. Loads the source shard and verifies decision_candidate is true.
  2. Assigns the next sequential ADR number (ADR-0001, ADR-0002, ...).
  3. Derives a title from the shard content or the --title argument.
  4. Writes the new ADR file under .agents/memory/adr/.
  5. Rebuilds INDEX.md from all ADR files in that directory.

ADR filename format:
  ADR-NNNN-<slug>.md

Usage:
  promote-adr.py <shard-path> --repo-root <path> [--title <title>]
  promote-adr.sh <shard-path>   (thin wrapper, resolves repo-root automatically)

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/promote-adr.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (
    ensure_dir,
    info,
    iso_date,
    load_event,
    relative_link,
    safe_main,
    slugify,
    utc_now,
    warn,
    write_text,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with shard (positional), repo_root
            (required), and optional title override.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("shard")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--title")
    return parser.parse_args()


def next_adr_id(adr_root: Path) -> str:
    """Return the next available ADR identifier by scanning existing ADR files.

    Scans for filenames matching ADR-NNNN-*.md, finds the highest NNNN, and
    returns a zero-padded four-digit identifier one above it.

    Args:
        adr_root: Path to the .agents/memory/adr/ directory.

    Returns:
        str: Next ADR identifier, e.g. "ADR-0003".
    """
    highest = 0
    for path in adr_root.glob("ADR-*.md"):
        match = re.match(r"ADR-(\d{4})", path.stem)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"ADR-{highest + 1:04d}"


def adr_title(event: dict[str, object], override: str | None) -> str:
    """Derive the ADR title from the source shard or an explicit override.

    Resolution order:
      1. The --title argument (if provided).
      2. First non-empty line from the shard's Why section.
      3. First non-empty line from the shard's What changed section.
      4. A generic fallback: "shared repo memory decision".

    Args:
        event: Loaded event shard dict (from load_event()).
        override: Explicit title string from the --title CLI argument, or None.

    Returns:
        str: Title string for the new ADR.
    """
    if override:
        return override
    why_lines = event["__sections"]["Why"]
    what_lines = event["__sections"]["What changed"]
    candidate = ""
    for line in why_lines + what_lines:
        candidate = line.lstrip("- ").strip()
        if candidate:
            break
    return candidate or "shared repo memory decision"


def parse_adr(path: Path) -> dict[str, str]:
    """Parse an existing ADR file into a flat dict of header fields.

    Reads:
      - Title from the H1 heading (first line).
      - Key: value pairs from the first 8 lines after the title.
      - Tags derived from the top-level directory names of "Related code paths"
        entries (e.g., "scripts" from "scripts/foo.py").

    This is a lightweight parser used only for INDEX.md generation; it does not
    need to handle the full ADR schema.

    Args:
        path: Path to an ADR-NNNN-*.md file.

    Returns:
        dict[str, str]: Flat mapping of field names to string values, always
            including "adr" (e.g., "ADR-0001"), "title", and "tags".
    """
    data = {
        "adr": path.stem.split("-", 2)[0] + "-" + path.stem.split("-", 2)[1],
        "title": path.stem,
    }
    if not path.exists():
        return data
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines:
        data["title"] = lines[0].removeprefix("# ").strip()
    # Parse key: value header fields from lines 2-8.
    for line in lines[1:8]:
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip().lower()] = value.strip()
    # Build tags from top-level directory names of related code paths.
    related_code_paths: list[str] = []
    capture = False
    for line in lines:
        if line == "## Related code paths":
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture and line.startswith("- "):
            related_code_paths.append(line.removeprefix("- ").strip())
    data["tags"] = (
        ",".join(sorted({path.split("/", 1)[0] for path in related_code_paths if path}))
        or "poc"
    )
    return data


def refresh_index(repo_root: Path) -> None:
    """Rebuild .agents/memory/adr/INDEX.md from all ADR-*.md files.

    Always rebuilds from scratch so the index stays consistent with the current
    set of ADR files.  Called automatically after every ADR promotion.

    Args:
        repo_root: Absolute path to the repository root.
    """
    adr_root = repo_root / ".agents/memory" / "adr"
    index_path = adr_root / "INDEX.md"
    rows = []
    for path in sorted(adr_root.glob("ADR-*.md")):
        data = parse_adr(path)
        # Strip the "ADR-NNNN " prefix from the title for the table cell -- the
        # ADR column already carries the identifier.
        title = (
            data["title"].split(" ", 1)[1] if " " in data["title"] else data["title"]
        )
        link_target = path.name
        adr_value = data.get(
            "adr", path.stem.split("-", 2)[0] + "-" + path.stem.split("-", 2)[1]
        )
        title_link = f"[{title}]({link_target})"
        rows.append(
            "| {adr} | {title} | {status} | {date} | {tags} | {must_read} | {supersedes} | {superseded_by} |".format(
                adr=adr_value,
                title=title_link,
                status=data.get("status", "accepted"),
                date=data.get("date", ""),
                tags=data.get("tags", "poc"),
                must_read=data.get("must read", "true"),
                supersedes=data.get("supersedes", ""),
                superseded_by=data.get("superseded by", ""),
            )
        )
    lines = [
        "# ADR index",
        "",
        "| ADR | Title | Status | Date | Tags | Must Read | Supersedes | Superseded By |",
        "|---|---|---|---|---|---|---|---|",
        *(rows or ["| - | None | - | - | - | - | - | - |"]),
        "",
    ]
    write_text(index_path, "\n".join(lines))


def main() -> int:
    """Entry point: promote a decision-candidate shard into a permanent ADR.

    Returns:
        int: 0 on success; 1 if the shard is not a decision candidate.
    """
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    event = load_event(Path(args.shard).resolve())

    # Guard: only decision-candidate shards may be promoted.
    if not event["decision_candidate"]:
        warn("shard is not marked as a decision candidate")
        return 1

    adr_root = ensure_dir(repo_root / ".agents/memory" / "adr")
    adr_id = next_adr_id(adr_root)
    title = adr_title(event, args.title)
    slug = slugify(title)
    adr_path = adr_root / f"{adr_id}-{slug}.md"

    timestamp_date = str(event["timestamp"])[:10] or iso_date(utc_now())
    related_event_name = event["__basename"]
    related_event_link = relative_link(adr_path, event["__path"], related_event_name)
    related_code_paths = [f"- {path}" for path in event.get("files_touched", [])]

    # Carry forward AI attribution from the source shard when present.
    ai_lines: list[str] = []
    for field in ("ai_generated", "ai_model", "ai_tool", "ai_surface", "ai_executor"):
        value = event.get(field)
        if value is not None:
            ai_lines.append(f"{field.replace('_', '-')}: {value}")

    # Write the ADR file using the canonical structure defined in the design doc.
    lines = [
        f"# {adr_id} {title}",
        "",
        "Status: accepted",
        f"Date: {timestamp_date}",
        f"Owners: {event['author']}",
        "Must read: true",
        "Supersedes: ",
        "Superseded by: ",
        *([line for line in ai_lines] if ai_lines else []),
        "",
        f"Purpose: {title}",
        f"Derived from: {related_event_link}",
        "",
        "## Context",
        "",
        *(event["__sections"]["Why"] or ["- None"]),
        "",
        "## Decision",
        "",
        *(event["__sections"]["What changed"] or ["- None"]),
        "",
        "## Consequences",
        "",
        *(event["__sections"]["Next"] or ["- None"]),
        "",
        "## Source memory events",
        "",
        f"- {related_event_link}",
        "",
        "## Related code paths",
        "",
        *(related_code_paths or ["- None"]),
        "",
    ]
    write_text(adr_path, "\n".join(lines))

    # Always rebuild the index after writing a new ADR so it stays consistent.
    refresh_index(repo_root)
    info(f"promoted {related_event_name} to {adr_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "PromoteADR"))
