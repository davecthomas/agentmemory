#!/usr/bin/env python3
"""enrich-shard.py -- Overwrite a raw shard with semantically enriched content.

This script is invoked by a subagent (claude -p, gemini, etc.) after
post-turn-notify.py writes a raw mechanical shard and saves an enrichment
context file.  It reads the context, rewrites the four body sections of the
shard with meaningful content, and rebuilds the daily summary.

The subagent provides the semantic reasoning -- this script handles the
file I/O and format constraints.

Enrichment context JSON schema:
  {
    "shard_path":      "<absolute path to the raw shard>",
    "repo_root":       "<absolute path to the repo root>",
    "assistant_text":  "<agent's response text from the turn>",
    "prompt":          "<user prompt that drove the turn>",
    "files_touched":   ["<path>", ...],
    "diff_summary":    "<compact git diff summary>"
  }

Usage:
  enrich-shard.py <context-json-path> \\
      --why "1-3 sentences about why this matters" \\
      --what "semantic summary of what was done" \\
      --evidence "concrete signals and citations" \\
      --next "follow-up work or implications" \\
      [--decision-candidate]

Install location after ./install.sh:
  ~/.agent/shared-repo-memory/enrich-shard.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import info, safe_main, warn, write_text


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with context_path and section content.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Overwrite a raw shard with enriched content."
    )
    parser.add_argument(
        "context_path",
        help="Path to the enrichment context JSON file.",
    )
    parser.add_argument(
        "--why",
        required=True,
        help="Enriched Why section content (1-3 sentences).",
    )
    parser.add_argument(
        "--what",
        required=True,
        help="Enriched What changed section content.",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        help="Enriched Evidence section content.",
    )
    parser.add_argument(
        "--next",
        required=True,
        help="Enriched Next section content.",
    )
    parser.add_argument(
        "--decision-candidate",
        action="store_true",
        default=False,
        help="Flag this shard as a decision candidate.",
    )
    return parser.parse_args()


def _load_context(context_path: Path) -> dict[str, object]:
    """Load and validate the enrichment context JSON.

    Args:
        context_path: Absolute path to the context file.

    Returns:
        dict: Parsed context with required fields.

    Raises:
        SystemExit: When the file is missing, unreadable, or lacks required fields.
    """
    if not context_path.exists():
        warn(f"enrichment context not found: {context_path}")
        sys.exit(1)
    try:
        context: dict[str, object] = json.loads(
            context_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        warn(f"failed to read enrichment context: {error}")
        sys.exit(1)
    required_keys: set[str] = {"shard_path", "repo_root"}
    missing_keys: set[str] = required_keys - set(context.keys())
    if missing_keys:
        warn(f"enrichment context missing required keys: {missing_keys}")
        sys.exit(1)
    return context


def _extract_frontmatter(shard_text: str) -> tuple[str, str]:
    """Split a shard into its frontmatter block and remaining body.

    Args:
        shard_text: Full text of the shard file.

    Returns:
        tuple: (frontmatter_block including --- delimiters, body after frontmatter).
    """
    lines: list[str] = shard_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return "", shard_text
    end_idx: int = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx == -1:
        return "", shard_text
    frontmatter_block: str = "\n".join(lines[: end_idx + 1])
    body: str = "\n".join(lines[end_idx + 1 :])
    return frontmatter_block, body


def _update_frontmatter_bool(frontmatter: str, field: str, value: bool) -> str:
    """Update a boolean field in frontmatter YAML.

    Args:
        frontmatter: The frontmatter block including --- delimiters.
        field: The YAML field name to update (e.g., "decision_candidate").
        value: The new boolean value to set.

    Returns:
        str: Updated frontmatter with the field set.
    """
    new_line: str = f"{field}: {'true' if value else 'false'}"
    for old_val in ("true", "false"):
        old_line: str = f"{field}: {old_val}"
        if old_line in frontmatter:
            return frontmatter.replace(old_line, new_line, 1)
    # Field not present in frontmatter; insert before the closing --- delimiter.
    lines: list[str] = frontmatter.split("\n")
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() == "---":
            return "\n".join(lines[:idx] + [new_line] + lines[idx:])
    return frontmatter


def _format_section_lines(raw_text: str) -> list[str]:
    """Convert raw enrichment text into bullet-prefixed lines.

    If the text already contains bullet lines (starting with -), preserve them.
    Otherwise wrap the text as a single bullet.

    Args:
        raw_text: Section content from the subagent.

    Returns:
        list[str]: Formatted bullet lines for the shard section.
    """
    str_stripped: str = raw_text.strip()
    if not str_stripped:
        return ["- No content provided."]
    lines: list[str] = [line for line in str_stripped.split("\n") if line.strip()]
    has_bullets: bool = any(line.strip().startswith("-") for line in lines)
    if has_bullets:
        return lines
    # No bullets detected; prefix each non-empty line so the shard stays consistent.
    return [f"- {line.strip()}" for line in lines]


def main() -> int:
    """Entry point: read context, overwrite shard with enriched content, rebuild summary.

    Returns:
        int: 0 on success, 1 on error.
    """
    args: argparse.Namespace = parse_args()
    context_path: Path = Path(args.context_path).resolve()
    context: dict[str, object] = _load_context(context_path)

    shard_path: Path = Path(str(context["shard_path"])).resolve()
    repo_root: Path = Path(str(context["repo_root"])).resolve()

    if not shard_path.exists():
        warn(f"shard file not found: {shard_path}")
        return 1

    # Read the existing raw shard and preserve its frontmatter.
    shard_text: str = shard_path.read_text(encoding="utf-8")
    frontmatter: str
    _body: str
    frontmatter, _body = _extract_frontmatter(shard_text)

    if not frontmatter:
        warn(f"shard has no valid frontmatter: {shard_path}")
        return 1

    # Update frontmatter boolean fields: mark as enriched and set decision_candidate.
    frontmatter = _update_frontmatter_bool(frontmatter, "decision_candidate", args.decision_candidate)
    frontmatter = _update_frontmatter_bool(frontmatter, "enriched", True)

    # Build enriched body sections.
    why_lines: list[str] = _format_section_lines(args.why)
    what_lines: list[str] = _format_section_lines(args.what)
    evidence_lines: list[str] = _format_section_lines(args.evidence)
    next_lines: list[str] = _format_section_lines(args.next)

    enriched_body: list[str] = [
        frontmatter,
        "",
        "## Why",
        "",
        *why_lines,
        "",
        "## Repo changes",
        "",
        *what_lines,
        "",
        "## Evidence",
        "",
        *evidence_lines,
        "",
        "## Next",
        "",
        *next_lines,
        "",
    ]
    write_text(shard_path, "\n".join(enriched_body))
    info(f"enriched {shard_path.relative_to(repo_root)}")

    # Rebuild the daily summary to reflect enriched content.
    date_str: str = shard_path.parent.parent.name  # daily/<date>/events/<shard>
    try:
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("rebuild-summary.py")),
                "--repo-root",
                str(repo_root),
                "--date",
                date_str,
            ],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        warn(f"summary rebuild after enrichment failed: {error.stderr[:200]}")

    # Stage the enriched shard and rebuilt summary.
    summary_path: Path = shard_path.parent.parent / "summary.md"
    try:
        subprocess.run(
            [
                "git",
                "add",
                str(shard_path.relative_to(repo_root)),
                str(summary_path.relative_to(repo_root)),
            ],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
        )
    except OSError:
        pass  # Non-fatal: shard is written even if staging fails.

    # Clean up the ephemeral context file.
    try:
        context_path.unlink()
    except OSError:
        pass  # Non-fatal.

    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "EnrichShard"))
