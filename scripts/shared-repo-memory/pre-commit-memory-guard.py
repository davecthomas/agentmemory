#!/usr/bin/env python3
"""pre-commit-memory-guard.py -- Block commits of unpublished shared memory artifacts.

This helper runs from the repo-local `pre-commit` Git hook installed by
bootstrap-repo.py. Its purpose is to enforce the publication boundary for the
pending-capture to published-checkpoint pipeline:

  1. Raw mechanical turn output is written under `.agents/memory/pending/`.
  2. Only the trusted checkpoint publish step may create committed files under
     `.agents/memory/daily/<date>/events/`.

The guard rejects a commit when either of these conditions is true:

  - A staged path lives under `.agents/memory/pending/`.
  - A staged daily event shard still contains `enriched: false`.

Usage:
  pre-commit-memory-guard.py [--repo-root <path>]
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from common import (
    PENDING_SHARDS_RELATIVE_DIR,
    parse_frontmatter,
    safe_main,
    try_repo_root,
    warn,
)

_EVENT_SHARD_PATTERN: re.Pattern[str] = re.compile(
    r"^\.agents/memory/daily/\d{4}-\d{2}-\d{2}/events/.+\.md$"
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the pre-commit guard.

    Returns:
        argparse.Namespace: Parsed arguments with an optional `repo_root`
            attribute used to override Git repository discovery.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Reject commits that stage unpublished shared memory artifacts."
    )
    parser.add_argument(
        "--repo-root",
        required=False,
        help="Path inside the target Git repository. Defaults to the current working directory.",
    )
    args: argparse.Namespace = parser.parse_args()
    return args


def staged_paths(repo_root: Path) -> list[str]:
    """Return repo-relative paths that are currently staged for commit.

    Args:
        repo_root: Absolute path to the Git repository root whose index should
            be inspected.

    Returns:
        list[str]: Deduplicated staged paths with additions, copies, modifications,
            or renames. Deleted paths are excluded because they have no staged file
            content to validate.
    """
    result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    list_str_paths: list[str] = []
    for raw_path in result.stdout.decode("utf-8", errors="replace").split("\0"):
        str_path: str = raw_path.strip()
        if not str_path:
            continue
        list_str_paths.append(str_path)
    list_str_unique_paths: list[str] = list(dict.fromkeys(list_str_paths))
    return list_str_unique_paths


def load_staged_text(repo_root: Path, str_path: str) -> str | None:
    """Return the staged file content for one repo-relative path.

    Args:
        repo_root: Absolute path to the Git repository root.
        str_path: Repo-relative path whose staged blob should be read from the index.

    Returns:
        str | None: UTF-8 staged file content when available, or None when Git
            cannot resolve the path from the index.
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "show", f":{str_path}"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    str_staged_text: str = result.stdout
    return str_staged_text


def is_daily_event_shard(str_path: str) -> bool:
    """Return True when a repo-relative path points to a committed daily event shard.

    Args:
        str_path: Repo-relative path staged in the index.

    Returns:
        bool: True when the path matches `.agents/memory/daily/<date>/events/*.md`;
            False for summaries, ADRs, pending files, or unrelated repo files.
    """
    bool_matches: bool = _EVENT_SHARD_PATTERN.match(str_path) is not None
    return bool_matches


def is_unenriched_event_shard_text(str_staged_text: str) -> bool:
    """Return True when staged shard frontmatter explicitly marks `enriched: false`.

    Args:
        str_staged_text: Full staged Markdown text for one daily event shard.

    Returns:
        bool: True when the parsed frontmatter contains `enriched: false`;
            False when the field is true, missing, or the frontmatter cannot be
            parsed by this helper.
    """
    try:
        dict_metadata, _body = parse_frontmatter(str_staged_text)
    except ValueError:
        return False
    object_enriched: object | None = dict_metadata.get("enriched")
    bool_is_unenriched: bool = object_enriched is False
    return bool_is_unenriched


def collect_guard_failures(repo_root: Path) -> list[str]:
    """Inspect staged files and return human-readable policy violations.

    Args:
        repo_root: Absolute path to the Git repository root.

    Returns:
        list[str]: Descriptions of each staged shared-memory artifact that violates
            the publication policy. An empty list means the commit may proceed.
    """
    list_str_failures: list[str] = []
    list_str_staged_paths: list[str] = staged_paths(repo_root)
    str_pending_prefix: str = f"{PENDING_SHARDS_RELATIVE_DIR}/"

    for str_path in list_str_staged_paths:
        if str_path.startswith(str_pending_prefix):
            list_str_failures.append(
                f"{str_path} is a pending raw shard; only published daily shards may be committed."
            )
            continue
        if not is_daily_event_shard(str_path):
            continue
        str_staged_text: str | None = load_staged_text(repo_root, str_path)
        if str_staged_text is None:
            list_str_failures.append(
                f"{str_path} could not be read from the index for shared-memory validation."
            )
            continue
        try:
            parse_frontmatter(str_staged_text)
        except ValueError:
            list_str_failures.append(
                f"{str_path} is missing valid frontmatter; shared-memory shards must stay well-formed."
            )
            continue
        if is_unenriched_event_shard_text(str_staged_text):
            list_str_failures.append(
                f"{str_path} is still marked `enriched: false`; raw shards must not be committed."
            )

    return list_str_failures


def main() -> int:
    """Run the shared-memory publication guard for the current Git commit.

    Returns:
        int: 0 when staged content passes validation, or 1 when the commit must
            be rejected because it includes pending or raw shared-memory artifacts.
    """
    args: argparse.Namespace = parse_args()
    path_repo_root: Path | None = try_repo_root(args.repo_root)
    if path_repo_root is None:
        return 0

    list_str_failures: list[str] = collect_guard_failures(path_repo_root)
    if not list_str_failures:
        return 0

    warn("pre-commit guard rejected staged shared-memory artifacts:")
    for str_failure in list_str_failures:
        warn(f"  - {str_failure}")
    warn(
        "Only trusted published daily event shards may be committed. Pending captures must stay local."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "PreCommitGuard"))
