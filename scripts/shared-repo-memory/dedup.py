#!/usr/bin/env python3
"""dedup.py -- Deduplication gates for the agentmemory capture pipeline.

This module owns all dedup decisions that prevent the same logical change from
producing multiple pending shards or multiple published checkpoints.  It is
imported by post-turn-notify.py (pending-capture gate) and publish-checkpoint.py
(publication gate).

Two independent dedup layers work together:

  1. **Diff-state gate** (pending capture time)
     Hashes the working-tree diff content and checks whether an identical hash
     was already captured for either the current workstream *or* the current
     branch.  The branch-scoped check is critical for runtimes like Codex that
     create a new thread (and therefore a new workstream_id) on every turn.

  2. **Published-event gate** (checkpoint publication time)
     Scans existing published events for the same date and branch.  If a
     checkpoint with high file-overlap already exists, publication is rejected.
     This is the safety net that catches proliferation even when upstream dedup
     and episode clustering fail.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from common import info, list_event_files, parse_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIFF_STATE_FILE: str = ".codex/local/last-shard-diff-state.json"
_UNTRACKED_SAMPLE_BYTES: int = 64 * 1024
_JACCARD_OVERLAP_THRESHOLD: float = 0.50
_BRANCH_KEY_PREFIX: str = "branch:"


# ---------------------------------------------------------------------------
# Git helpers (bounded, safe for synchronous hook use)
# ---------------------------------------------------------------------------


def file_is_tracked(repo_root: Path, str_path: str) -> bool:
    """Return True when a repo-relative path is tracked by Git."""
    try:
        result: subprocess.CompletedProcess[bytes] = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str_path],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _untracked_file_fingerprint(path_file: Path) -> bytes:
    """Return a bounded content fingerprint for one untracked file.

    Records file size plus head and tail samples so hashing stays bounded
    while still tracking meaningful changes for typical source files.
    """
    int_sample: int = _UNTRACKED_SAMPLE_BYTES
    path_stat = path_file.stat()
    int_size: int = path_stat.st_size
    with path_file.open("rb") as fh:
        bytes_head: bytes = fh.read(int_sample)
        bytes_tail: bytes = b""
        if int_size > int_sample:
            fh.seek(max(int_size - int_sample, 0))
            bytes_tail = fh.read(int_sample)
    return f"SIZE:{int_size}\0".encode() + bytes_head + b"\0TAIL\0" + bytes_tail


# ---------------------------------------------------------------------------
# Diff fingerprinting
# ---------------------------------------------------------------------------


def diff_fingerprint(repo_root: Path, files: list[str]) -> str:
    """Return a stable hash of the current working-tree changes for the given files.

    Includes both tracked Git diff output and bounded fingerprints of untracked
    files so new-file turns do not collapse to the same empty-diff hash.

    Returns an empty string on any error (callers treat empty as "unhashable,
    do not deduplicate").
    """
    try:
        digest = hashlib.md5()
        result_unstaged = subprocess.run(
            ["git", "diff", "HEAD", "--"] + files,
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        result_staged = subprocess.run(
            ["git", "diff", "--cached", "--"] + files,
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        digest.update(result_unstaged.stdout)
        digest.update(result_staged.stdout)
        for str_path in files:
            if file_is_tracked(repo_root, str_path):
                continue
            path_file: Path = repo_root / str_path
            digest.update(b"\0UNTRACKED\0")
            digest.update(str_path.encode("utf-8", errors="replace"))
            if path_file.is_file():
                digest.update(_untracked_file_fingerprint(path_file))
            elif path_file.is_dir():
                digest.update(b"<directory>")
            else:
                digest.update(b"<missing>")
        return digest.hexdigest()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Diff-state persistence (local-only, never committed)
# ---------------------------------------------------------------------------


def _state_path(repo_root: Path) -> Path:
    return repo_root / _DIFF_STATE_FILE


def _load_state(repo_root: Path) -> dict[str, str]:
    try:
        return json.loads(_state_path(repo_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(repo_root: Path, state: dict[str, str]) -> None:
    path = _state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pending-capture dedup gate
# ---------------------------------------------------------------------------


def already_captured(
    repo_root: Path,
    workstream_id: str,
    branch: str,
    current_hash: str,
) -> bool:
    """Return True if this diff was already captured for this workstream or branch.

    Checks two keys in the state file:
      - The workstream key (e.g. ``thread-<uuid>``) for same-session dedup.
      - The branch key (e.g. ``branch:feature/foo``) for cross-session dedup.

    The branch-scoped check is the fix for Codex, where every turn creates a
    new thread_id.  Without it, the same diff is captured hundreds of times
    under different workstream keys.
    """
    if not current_hash:
        return False
    state: dict[str, str] = _load_state(repo_root)
    branch_key: str = f"{_BRANCH_KEY_PREFIX}{branch}"
    if state.get(workstream_id) == current_hash:
        info(f"dedup: diff already captured for workstream {workstream_id}")
        return True
    if state.get(branch_key) == current_hash:
        info(f"dedup: diff already captured for branch {branch}")
        return True
    return False


def record_capture(
    repo_root: Path,
    workstream_id: str,
    branch: str,
    diff_hash: str,
) -> None:
    """Record a successful capture under both the workstream and branch keys."""
    if not diff_hash:
        return
    state: dict[str, str] = _load_state(repo_root)
    state[workstream_id] = diff_hash
    state[f"{_BRANCH_KEY_PREFIX}{branch}"] = diff_hash
    _save_state(repo_root, state)


# ---------------------------------------------------------------------------
# Published-event dedup gate (safety net at publication time)
# ---------------------------------------------------------------------------


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Return the Jaccard similarity coefficient for two string sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def published_event_exists(
    repo_root: Path,
    date: str,
    branch: str,
    files_touched: list[str],
) -> bool:
    """Return True if a published event with high overlap already exists today.

    Scans ``daily/<date>/events/`` for any checkpoint that shares the same
    branch and has Jaccard file-overlap above the threshold.  This prevents
    the same logical change from being published as multiple checkpoints even
    when upstream dedup and clustering fail.
    """
    day_dir: Path = repo_root / ".agents" / "memory" / "daily" / date
    if not day_dir.is_dir():
        return False

    set_candidate_files: set[str] = set(files_touched)
    if not set_candidate_files:
        return False

    list_event_paths: list[Path] = list_event_files(day_dir)
    for path_event in list_event_paths:
        try:
            str_text: str = path_event.read_text(encoding="utf-8")
            dict_metadata: dict[str, Any]
            dict_metadata, _body = parse_frontmatter(str_text)
        except (OSError, ValueError):
            continue

        str_event_branch: str = str(dict_metadata.get("branch", "")).strip()
        if str_event_branch != branch:
            continue

        object_event_files: object = dict_metadata.get("files_touched", [])
        if not isinstance(object_event_files, list):
            continue
        set_event_files: set[str] = {str(f) for f in object_event_files}

        similarity: float = _jaccard_similarity(set_candidate_files, set_event_files)
        if similarity >= _JACCARD_OVERLAP_THRESHOLD:
            info(
                f"dedup: existing event {path_event.name} overlaps "
                f"{similarity:.0%} on branch {branch}"
            )
            return True

    return False
