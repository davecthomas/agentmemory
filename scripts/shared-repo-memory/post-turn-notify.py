#!/usr/bin/env python3
"""post-turn-notify.py -- Post-turn hook for the shared repo-memory system.

This script fires after every agent turn. Its job is to decide whether the turn
changed repo files and, if so, write a local pending capture containing only the
mechanical repo facts needed for trusted checkpoint publication later.

The file-changing turn gate
---------------------------
A pending local-only capture is written only when repo files changed in the
working tree (files_touched is non-empty). Conversational turns with no repo
changes, even long discussions that mention ADRs or decisions, produce no
capture. This prevents the memory from filling up with noise and false-positive
decision candidates.

Triggered by:
  - Claude Code:  Stop hook (CLAUDECODE=1 env var, hookEventName == "Stop")
  - Gemini CLI:   AfterAgent hook (hookEventName == "AfterAgent")
  - Codex CLI:    Invoked directly via scripts/shared-repo-memory/notify-wrapper.sh

After writing the pending shard, this script may:
  1. Save a privacy-safe checkpoint context manifest and spawn an async
     subagent to evaluate whether a durable episode checkpoint should be
     published into `.agents/memory/daily/<date>/events/`.
  2. Spawn an ADR inspection subagent when changed design docs were touched.

The raw pending shard is local-only and must never be committed. Publication,
summary rebuild, and staging happen only inside publish-checkpoint.py after a
bounded episode cluster passes semantic validation.

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/post-turn-notify.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import TextIO

from adapters import ClaudeAdapter, detect_adapter, detect_adapter_from_hook_event
from common import (
    CHECKPOINT_CONTEXT_RELATIVE_DIR,
    PENDING_SHARDS_RELATIVE_DIR,
    append_hook_trace,
    author_slug,
    changed_repo_files,
    current_branch,
    ensure_dir,
    find_first,
    flatten_strings,
    format_log_prefix,
    info,
    parse_frontmatter,
    render_frontmatter,
    runtime_provider_version,
    safe_main,
    set_runtime_log_context,
    slugify,
    try_repo_root,
    utc_now,
    utc_timestamp,
    warn,
    write_text,
)
from episode_graph import rebuild_episode_graph
from models import HookResponse


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with optional repo_root attribute.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=False)
    return parser.parse_args()


def stable_identifier(prefix: str, payload: dict[str, object]) -> str:
    """Derive a stable short identifier fragment from a JSON payload hash.

    Used when the hook payload does not provide a thread_id or turn_id directly.
    The SHA-1 of the serialized payload provides a deterministic, collision-
    resistant identifier that is stable across retries with the same payload.
    The prefix is used only as a hash salt so thread and turn identifiers do
    not collide when they are derived from the same payload.

    Args:
        prefix: Short namespace string such as "thread" or "turn".
        payload: JSON-serialisable dict to hash.

    Returns:
        str: Ten-character hexadecimal identifier fragment with no semantic
            prefix attached.
    """
    digest_payload: dict[str, object] = {"prefix": prefix, "payload": payload}
    digest = hashlib.sha1(
        json.dumps(digest_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:10]


def _normalize_identifier_component(
    str_raw_identifier: str, str_expected_prefix: str
) -> str:
    """Normalize a thread or turn identifier for shard filenames and metadata.

    Args:
        str_raw_identifier: Identifier from the runtime payload or a generated
            fallback value.
        str_expected_prefix: Semantic prefix such as "thread" or "turn" that
            should not be duplicated in the canonical identifier component.

    Returns:
        str: Normalized identifier with spaces replaced by underscores and one
            leading semantic prefix removed when present.
    """
    str_normalized_identifier: str = str_raw_identifier.strip().replace(" ", "_")
    str_prefix: str = f"{str_expected_prefix}_"
    if str_normalized_identifier.lower().startswith(str_prefix):
        str_normalized_identifier = str_normalized_identifier[len(str_prefix) :]
    return str_normalized_identifier


# ---------------------------------------------------------------------------
# Diff-hash deduplication
# ---------------------------------------------------------------------------

_DIFF_STATE_FILE = ".codex/local/last-shard-diff-state.json"
_UNTRACKED_FILE_HASH_SAMPLE_BYTES: int = 64 * 1024


def _file_is_tracked(repo_root: Path, str_path: str) -> bool:
    """Return True when a path is already tracked by Git in the given repo.

    Args:
        repo_root: Absolute path to the repository root.
        str_path: Repo-relative file path to check.

    Returns:
        bool: True when git ls-files resolves the path; False for untracked files
            or any lookup error.
    """
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

    The post-turn hook runs synchronously, so dedupe hashing must avoid loading
    large untracked files fully into memory. This helper records file size plus
    head and tail samples, which keeps hashing bounded while still tracking
    meaningful changes for typical source files and documents.

    Args:
        path_file: Absolute path to the untracked file.

    Returns:
        bytes: Stable byte payload suitable for hashing into the turn diff state.
    """
    int_sample_bytes: int = _UNTRACKED_FILE_HASH_SAMPLE_BYTES
    path_stat = path_file.stat()
    int_file_size: int = path_stat.st_size
    with path_file.open("rb") as file_handle:
        bytes_head: bytes = file_handle.read(int_sample_bytes)
        bytes_tail: bytes = b""
        if int_file_size > int_sample_bytes:
            int_tail_offset: int = max(int_file_size - int_sample_bytes, 0)
            file_handle.seek(int_tail_offset)
            bytes_tail = file_handle.read(int_sample_bytes)
    bytes_size_prefix: bytes = f"SIZE:{int_file_size}\0".encode()
    bytes_tail_separator: bytes = b"\0TAIL\0"
    bytes_fingerprint: bytes = (
        bytes_size_prefix + bytes_head + bytes_tail_separator + bytes_tail
    )
    return bytes_fingerprint


def _diff_hash(repo_root: Path, files: list[str]) -> str:
    """Return a stable hash of the current change content for the given files.

    The hash includes both tracked Git diff output and a bounded fingerprint of
    any untracked files. This prevents new-file turns from collapsing to the
    same empty-diff hash while keeping synchronous hook memory use bounded on
    large local files.
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
            if _file_is_tracked(repo_root, str_path):
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


def _load_diff_state(repo_root: Path) -> dict:
    state_path = repo_root / _DIFF_STATE_FILE
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_diff_state(repo_root: Path, thread_id: str, diff_hash_val: str) -> None:
    state_path = repo_root / _DIFF_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = _load_diff_state(repo_root)
    state[thread_id] = diff_hash_val
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _already_captured(repo_root: Path, thread_id: str, current_hash: str) -> bool:
    """Return True if this exact diff was already captured in a shard this session."""
    if not current_hash:
        return False
    state = _load_diff_state(repo_root)
    return state.get(thread_id) == current_hash


# ---------------------------------------------------------------------------
# Git diff summary for pending-capture evidence
# ---------------------------------------------------------------------------


def _diff_summary(repo_root: Path, files: list[str]) -> str:
    """Return a compact human-readable summary of what changed in the given files.

    Runs 'git diff HEAD --stat' for a one-liner per file, then pulls up to
    three representative changed lines (additions starting with '+') from the
    full diff as supporting detail.  Returns empty string on any failure.
    """
    try:
        list_str_untracked_files: list[str] = [
            str_path for str_path in files if not _file_is_tracked(repo_root, str_path)
        ]
        stat = subprocess.run(
            ["git", "diff", "HEAD", "--stat", "--"] + files,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not stat:
            # Try staged changes too
            stat = subprocess.run(
                ["git", "diff", "--cached", "--stat", "--"] + files,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        if not stat and list_str_untracked_files:
            list_str_preview_paths: list[str] = list_str_untracked_files[:3]
            str_preview: str = ", ".join(list_str_preview_paths)
            if len(list_str_untracked_files) > len(list_str_preview_paths):
                str_preview += ", ..."
            count: int = len(list_str_untracked_files)
            noun: str = "file" if count == 1 else "files"
            stat = f"{count} new untracked {noun}: {str_preview}"
        # Pull a few representative added lines from the diff
        diff_text = subprocess.run(
            ["git", "diff", "HEAD", "-U0", "--"] + files,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        added = [
            ln[1:].strip()
            for ln in diff_text.splitlines()
            if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()
        ][:3]
        parts = []
        if stat:
            parts.append(stat.splitlines()[-1] if "\n" in stat else stat)
        parts.extend(added)
        return "; ".join(parts)
    except Exception:
        return ""


def parse_timestamp_from_shard_name(str_shard_name: str) -> str:
    """Return the canonical ISO timestamp encoded in a shard filename.

    Args:
        str_shard_name: Basename such as
            `2026-04-07T18-42-00Z--alice--thread_x--turn_y.md`.

    Returns:
        str: Timestamp in the form `YYYY-MM-DDTHH:MM:SSZ`.
    """
    str_raw_timestamp: str = str_shard_name.split("--", 1)[0]
    str_date_part: str
    str_time_part: str
    str_date_part, str_time_part = str_raw_timestamp.split("T", 1)
    str_timestamp: str = f"{str_date_part}T{str_time_part.replace('-', ':')}"
    return str_timestamp


def find_existing_turn_artifact(
    repo_root: Path, thread_id: str, turn_id: str
) -> Path | None:
    """Return an existing pending or published shard for the current thread+turn.

    Published daily shards take precedence over pending raw shards so retries use
    the already-published timestamp when both somehow exist.

    Args:
        repo_root: Absolute path to the repository root.
        thread_id: Stable thread identifier for the current turn.
        turn_id: Stable turn identifier for the current turn.

    Returns:
        Path | None: Existing artifact path when one already exists, or None when
            this is the first capture for the thread+turn combination.
    """
    str_pattern: str = f"*--thread_{thread_id}--turn_{turn_id}.md"
    path_daily_root: Path = repo_root / ".agents" / "memory" / "daily"
    list_path_published_matches: list[Path] = sorted(
        path_daily_root.glob(f"*/events/{str_pattern}")
    )
    if list_path_published_matches:
        path_existing_published: Path = list_path_published_matches[0]
        return path_existing_published

    path_pending_root: Path = repo_root / PENDING_SHARDS_RELATIVE_DIR
    list_path_pending_matches: list[Path] = sorted(
        path_pending_root.glob(f"*/{str_pattern}")
    )
    if list_path_pending_matches:
        path_existing_pending: Path = list_path_pending_matches[0]
        return path_existing_pending

    return None


def published_shard_path(repo_root: Path, timestamp: str, basename: str) -> Path:
    """Return the durable published shard path for one shard basename.

    Args:
        repo_root: Absolute path to the repository root.
        timestamp: Canonical UTC timestamp for the shard.
        basename: Shard filename stem without the `.md` suffix.

    Returns:
        Path: Absolute path under `.agents/memory/daily/<date>/events/`.
    """
    path_published_shard: Path = (
        repo_root
        / ".agents"
        / "memory"
        / "daily"
        / timestamp[:10]
        / "events"
        / f"{basename}.md"
    )
    return path_published_shard


def pending_shard_path(repo_root: Path, timestamp: str, basename: str) -> Path:
    """Return the ignored pending shard path for one shard basename.

    Args:
        repo_root: Absolute path to the repository root.
        timestamp: Canonical UTC timestamp for the shard.
        basename: Shard filename stem without the `.md` suffix.

    Returns:
        Path: Absolute path under `.agents/memory/pending/<date>/`.
    """
    path_pending_shard: Path = (
        repo_root / PENDING_SHARDS_RELATIVE_DIR / timestamp[:10] / f"{basename}.md"
    )
    return path_pending_shard


# ---------------------------------------------------------------------------
# Design doc detection patterns
# ---------------------------------------------------------------------------

_DOC_EXTENSIONS: set[str] = {".md", ".rst", ".mdx", ".txt"}

_DESIGN_DOC_PATTERNS: list[str] = [
    "design",
    "spec",
    "arch",
    "adr",
]


def _is_design_doc(file_path: str) -> bool:
    """Return True if a file path looks like a design document.

    A file qualifies when it lives under docs/ with a doc extension, or when
    its path contains a design-related keyword AND has a doc extension.  This
    avoids false positives on code files whose paths happen to contain
    substrings like "spec" or "adr" (e.g., skills/adr-inspector/SKILL.md
    is a skill, not a design doc).

    Args:
        file_path: Repo-relative file path.

    Returns:
        bool: True when the path matches design doc heuristics.
    """
    str_lower: str = file_path.lower()
    ext: str = Path(str_lower).suffix
    if ext not in _DOC_EXTENSIONS:
        return False
    # Files under docs/ are always design docs.
    if str_lower.startswith("docs/"):
        return True
    # Files with design-related keywords in the filename (not directory) qualify.
    filename: str = Path(str_lower).stem
    return any(pattern in filename for pattern in _DESIGN_DOC_PATTERNS)


# ---------------------------------------------------------------------------
# Async subagent spawning: checkpoint evaluation and ADR inspection
# ---------------------------------------------------------------------------


def _open_enrichment_log(repo_root: Path) -> TextIO:
    """Open (or create) the background memory log file for subprocess output.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        File handle for the background memory log.
    """
    log_dir: Path = repo_root / ".agents" / "memory" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return open(log_dir / "enrichment.log", "a")  # noqa: SIM115


def _checkpoint_context_dir(repo_root: Path) -> Path:
    """Return the ignored directory used for checkpoint context manifests.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Path: Absolute path to the local-only checkpoint context directory.
    """
    path_context_dir: Path = ensure_dir(repo_root / CHECKPOINT_CONTEXT_RELATIVE_DIR)
    return path_context_dir


def _path_scope_keys(list_str_paths: list[str]) -> set[str]:
    """Return coarse path-scope keys used to group branch-scoped pending captures.

    Args:
        list_str_paths: Repo-relative file paths touched by one pending capture.

    Returns:
        set[str]: Top-level or top-two-level path keys used to approximate
            whether two pending captures likely belong to the same effort.
    """
    set_str_scope_keys: set[str] = set()
    for str_path in list_str_paths:
        path_item: Path = Path(str_path)
        tuple_str_parts: tuple[str, ...] = path_item.parts
        if not tuple_str_parts:
            continue
        if len(tuple_str_parts) == 1:
            set_str_scope_keys.add(tuple_str_parts[0])
            continue
        set_str_scope_keys.add("/".join(tuple_str_parts[:2]))
    return set_str_scope_keys


def _workstream_identity(
    str_explicit_thread_id: str, str_branch: str
) -> tuple[str, str]:
    """Return the stable workstream identifier and scope for one turn.

    Args:
        str_explicit_thread_id: Runtime-provided thread identifier after
            normalization, or an empty string when the runtime lacks one.
        str_branch: Current repository branch name.

    Returns:
        tuple[str, str]: `(workstream_id, workstream_scope)` where scope is
            either `thread` or `branch`.
    """
    if str_explicit_thread_id:
        return f"thread-{str_explicit_thread_id}", "thread"
    return f"branch-{slugify(str_branch)}", "branch"


def _load_pending_metadata(path_pending_shard: Path) -> dict[str, object] | None:
    """Load frontmatter metadata from one pending capture.

    Args:
        path_pending_shard: Absolute path to the pending Markdown shard.

    Returns:
        dict[str, object] | None: Parsed frontmatter metadata, or None when the
            shard is unreadable or malformed.
    """
    try:
        str_pending_text: str = path_pending_shard.read_text(encoding="utf-8")
        dict_metadata: dict[str, object]
        _body: str
        dict_metadata, _body = parse_frontmatter(str_pending_text)
        return dict_metadata
    except (OSError, ValueError):
        return None


def _pending_bundle_entry(path_pending_shard: Path) -> dict[str, object] | None:
    """Build one structured bundle entry from a pending capture file.

    Args:
        path_pending_shard: Absolute path to the pending capture.

    Returns:
        dict[str, object] | None: Bundle metadata for the checkpoint context, or
            None when the pending capture cannot be parsed.
    """
    dict_metadata: dict[str, object] | None = _load_pending_metadata(path_pending_shard)
    if dict_metadata is None:
        return None
    object_files_touched: object = dict_metadata.get("files_touched", [])
    object_design_docs_touched: object = dict_metadata.get("design_docs_touched", [])
    object_verification: object = dict_metadata.get("verification", [])
    dict_bundle_entry: dict[str, object] = {
        "path": str(path_pending_shard),
        "timestamp": str(dict_metadata.get("timestamp", "")),
        "branch": str(dict_metadata.get("branch", "")),
        "thread_id": str(dict_metadata.get("thread_id", "")),
        "turn_id": str(dict_metadata.get("turn_id", "")),
        "workstream_id": str(dict_metadata.get("workstream_id", "")),
        "workstream_scope": str(dict_metadata.get("workstream_scope", "")),
        "files_touched": (
            [str(item) for item in object_files_touched]
            if isinstance(object_files_touched, list)
            else []
        ),
        "design_docs_touched": (
            [str(item) for item in object_design_docs_touched]
            if isinstance(object_design_docs_touched, list)
            else []
        ),
        "verification": (
            [str(item) for item in object_verification]
            if isinstance(object_verification, list)
            else []
        ),
        "diff_summary": str(dict_metadata.get("diff_summary", "")),
    }
    return dict_bundle_entry


def _collect_related_pending_shards(
    repo_root: Path,
    path_current_pending_shard: Path,
    str_workstream_id: str,
    str_workstream_scope: str,
    files_touched: list[str],
    *,
    limit: int = 5,
) -> list[Path]:
    """Return a bounded chronological bundle of related pending captures.

    Args:
        repo_root: Absolute repository root.
        path_current_pending_shard: Pending capture created by the latest turn.
        str_workstream_id: Stable workstream identifier for the latest turn.
        str_workstream_scope: `thread` or `branch`.
        files_touched: Repo-relative files changed by the latest turn.
        limit: Maximum number of pending captures to include in the bundle.

    Returns:
        list[Path]: Chronologically sorted pending-capture paths. The current
            pending capture is always included.
    """
    path_pending_root: Path = repo_root / PENDING_SHARDS_RELATIVE_DIR
    list_path_candidates: list[Path] = sorted(path_pending_root.glob("*/*.md"))
    set_str_current_scope_keys: set[str] = _path_scope_keys(files_touched)
    list_tuple_candidate_rows: list[tuple[str, str, Path]] = []

    for path_candidate in list_path_candidates:
        dict_candidate_metadata: dict[str, object] | None = _load_pending_metadata(
            path_candidate
        )
        if dict_candidate_metadata is None:
            continue
        if str(dict_candidate_metadata.get("workstream_id", "")) != str_workstream_id:
            continue
        if (
            path_candidate != path_current_pending_shard
            and str_workstream_scope == "branch"
        ):
            object_candidate_files: object = dict_candidate_metadata.get(
                "files_touched", []
            )
            list_str_candidate_files: list[str] = (
                [str(item) for item in object_candidate_files]
                if isinstance(object_candidate_files, list)
                else []
            )
            set_str_candidate_scope_keys: set[str] = _path_scope_keys(
                list_str_candidate_files
            )
            if (
                set_str_current_scope_keys
                and set_str_candidate_scope_keys
                and set_str_current_scope_keys.isdisjoint(set_str_candidate_scope_keys)
            ):
                continue
        str_timestamp: str = str(dict_candidate_metadata.get("timestamp", ""))
        list_tuple_candidate_rows.append(
            (str_timestamp, path_candidate.name, path_candidate)
        )

    list_tuple_candidate_rows.sort()
    list_path_other_shards: list[Path] = [
        path_candidate
        for _str_timestamp, _str_name, path_candidate in list_tuple_candidate_rows
        if path_candidate != path_current_pending_shard
    ]
    list_path_selected_shards: list[Path] = list_path_other_shards[-max(limit - 1, 0) :]
    list_path_selected_shards.append(path_current_pending_shard)
    list_path_selected_shards = sorted(dict.fromkeys(list_path_selected_shards))
    return list_path_selected_shards


def _recent_summary_paths(repo_root: Path, *, limit: int = 3) -> list[str]:
    """Return absolute paths to the most recent daily summaries.

    Args:
        repo_root: Absolute repository root.
        limit: Maximum number of summaries to include.

    Returns:
        list[str]: Newest-first absolute summary paths.
    """
    path_daily_root: Path = repo_root / ".agents" / "memory" / "daily"
    if not path_daily_root.exists():
        return []
    list_path_recent_summaries: list[str] = []
    list_path_day_dirs: list[Path] = sorted(
        [
            path_day_dir
            for path_day_dir in path_daily_root.iterdir()
            if path_day_dir.is_dir()
        ],
        reverse=True,
    )
    for path_day_dir in list_path_day_dirs:
        path_summary: Path = path_day_dir / "summary.md"
        if not path_summary.exists():
            continue
        list_path_recent_summaries.append(str(path_summary))
        if len(list_path_recent_summaries) >= limit:
            break
    return list_path_recent_summaries


def _episode_bundle_entries(
    dict_episode_manifest: dict[str, object],
) -> tuple[list[str], list[dict[str, object]]]:
    """Extract privacy-safe bundle entries from one active episode manifest.

    Args:
        dict_episode_manifest: Episode-cluster manifest returned by
            episode_graph.rebuild_episode_graph().

    Returns:
        tuple[list[str], list[dict[str, object]]]: Absolute pending-capture
            paths plus structured member-node metadata suitable for the local
            checkpoint context JSON.
    """
    object_member_paths: object = dict_episode_manifest.get(
        "member_pending_shard_paths", []
    )
    list_str_member_paths: list[str] = (
        [
            str(str_item).strip()
            for str_item in object_member_paths
            if str(str_item).strip()
        ]
        if isinstance(object_member_paths, list)
        else []
    )

    object_member_nodes: object = dict_episode_manifest.get("member_nodes", [])
    list_dict_bundle_entries: list[dict[str, object]] = []
    if not isinstance(object_member_nodes, list):
        return list_str_member_paths, list_dict_bundle_entries

    object_member_node: object
    for object_member_node in object_member_nodes:
        if not isinstance(object_member_node, dict):
            continue
        dict_bundle_entry: dict[str, object] = {
            "path": str(object_member_node.get("path", "")),
            "timestamp": str(object_member_node.get("timestamp", "")),
            "branch": str(object_member_node.get("branch", "")),
            "thread_id": str(object_member_node.get("thread_id", "")),
            "turn_id": str(object_member_node.get("turn_id", "")),
            "workstream_id": str(object_member_node.get("workstream_id", "")),
            "workstream_scope": str(object_member_node.get("workstream_scope", "")),
            "files_touched": (
                list(object_member_node.get("files_touched", []))
                if isinstance(object_member_node.get("files_touched", []), list)
                else []
            ),
            "design_docs_touched": (
                list(object_member_node.get("design_docs_touched", []))
                if isinstance(object_member_node.get("design_docs_touched", []), list)
                else []
            ),
            "verification": (
                list(object_member_node.get("verification", []))
                if isinstance(object_member_node.get("verification", []), list)
                else []
            ),
            "diff_summary": str(object_member_node.get("diff_summary", "")),
            "path_scope_keys": (
                list(object_member_node.get("path_scope_keys", []))
                if isinstance(object_member_node.get("path_scope_keys", []), list)
                else []
            ),
            "issue_ids": (
                list(object_member_node.get("issue_ids", []))
                if isinstance(object_member_node.get("issue_ids", []), list)
                else []
            ),
            "validation_signals": (
                list(object_member_node.get("validation_signals", []))
                if isinstance(object_member_node.get("validation_signals", []), list)
                else []
            ),
            "related_adrs": (
                list(object_member_node.get("related_adrs", []))
                if isinstance(object_member_node.get("related_adrs", []), list)
                else []
            ),
        }
        list_dict_bundle_entries.append(dict_bundle_entry)

    return list_str_member_paths, list_dict_bundle_entries


def _write_local_notify_metadata(
    repo_root: Path,
    *,
    adapter: type,
    req: object,
    files_touched: list[str],
    design_docs_touched: list[str],
    pending_shard_path: Path | None = None,
    published_shard_path: Path | None = None,
    workstream_id: str = "",
    workstream_scope: str = "",
    episode_id: str = "",
    episode_scope: str = "",
    episode_manifest_path: Path | None = None,
    episode_member_count: int = 0,
) -> None:
    """Persist a sanitized local debug record for the latest notify invocation.

    Args:
        repo_root: Absolute repository root.
        adapter: Detected runtime adapter class.
        req: Normalized hook request object from the adapter.
        files_touched: Repo-relative changed files for this turn.
        design_docs_touched: Repo-relative design documents touched by the turn.
        pending_shard_path: Optional pending shard path created for this turn.
        published_shard_path: Optional published checkpoint path reserved for this turn.
        workstream_id: Stable workstream identifier.
        workstream_scope: `thread` or `branch`.
        episode_id: Stable active episode-cluster identifier when graph rebuild
            succeeds for this pending capture.
        episode_scope: Dominant episode scope such as `thread`, `branch`, or
            `mixed`.
        episode_manifest_path: Absolute path to the local episode-cluster
            manifest for this pending capture.
        episode_member_count: Number of pending captures currently grouped into
            the active episode cluster.

    Returns:
        None: The local metadata file is overwritten in place.
    """
    local_root: Path = ensure_dir(repo_root / ".codex" / "local")
    dict_metadata: dict[str, object] = {
        "runtime": adapter.agent_id(),
        "runtime_version": runtime_provider_version(adapter.agent_id()),
        "hook_event": getattr(req, "hook_event", ""),
        "session_id": getattr(req, "session_id", ""),
        "thread_id": getattr(req, "thread_id", ""),
        "turn_id": getattr(req, "turn_id", ""),
        "model": getattr(req, "model", ""),
        "files_touched": files_touched,
        "design_docs_touched": design_docs_touched,
        "workstream_id": workstream_id,
        "workstream_scope": workstream_scope,
        "episode_id": episode_id,
        "episode_scope": episode_scope,
        "episode_member_count": episode_member_count,
    }
    if pending_shard_path is not None:
        dict_metadata["pending_shard_path"] = str(
            pending_shard_path.relative_to(repo_root)
        )
    if published_shard_path is not None:
        dict_metadata["published_shard_path"] = str(
            published_shard_path.relative_to(repo_root)
        )
    if episode_manifest_path is not None:
        dict_metadata["episode_manifest_path"] = str(
            episode_manifest_path.relative_to(repo_root)
        )
    write_text(
        local_root / "last-notify-metadata.json",
        json.dumps(dict_metadata, indent=2, sort_keys=True) + "\n",
    )


def _resolve_bootstrap_command(
    adapter: type,
    skill_content: str,
    task: str,
    repo_root: Path,
) -> tuple[list[str] | None, str, str]:
    """Resolve the concrete CLI command and runtime metadata for a subagent.

    Args:
        adapter: Requested runtime adapter for the current hook invocation.
        skill_content: Full skill instructions provided to the subagent CLI.
        task: User task string passed to the spawned subagent.
        repo_root: Absolute path to the repository root.

    Returns:
        tuple[list[str] | None, str, str]: The CLI command to execute, the
            launcher runtime id, and the launcher runtime version. When no
            launch path exists, the command element is None and the metadata is
            set to non-agent fallback values.
    """
    list_str_cmd: list[str] | None = adapter.build_bootstrap_command(
        skill_content, task, repo_root
    )
    str_launcher_agent_id: str = adapter.agent_id()
    if list_str_cmd is None:
        list_str_cmd = ClaudeAdapter.build_bootstrap_command(
            skill_content, task, repo_root
        )
        str_launcher_agent_id = ClaudeAdapter.agent_id()
    if list_str_cmd is None:
        return None, "system", "n/a"

    str_launcher_provider_version: str = runtime_provider_version(str_launcher_agent_id)
    return list_str_cmd, str_launcher_agent_id, str_launcher_provider_version


def _subagent_env(
    str_launcher_agent_id: str, str_launcher_provider_version: str
) -> dict[str, str]:
    """Build environment overrides for spawned memory background subprocesses.

    Args:
        str_launcher_agent_id: Runtime that is launching the subagent, such as
            "claude" or "gemini".
        str_launcher_provider_version: Resolved CLI version for the launcher.

    Returns:
        dict[str, str]: Copy of os.environ plus explicit agentmemory runtime
            metadata consumed by common.py log helpers in descendant processes.
    """
    dict_env: dict[str, str] = dict(os.environ)
    dict_env["AGENTMEMORY_RUNTIME_ID"] = str_launcher_agent_id
    dict_env["AGENTMEMORY_RUNTIME_VERSION"] = str_launcher_provider_version
    dict_env["SHARED_REPO_MEMORY_AGENT_ID"] = str_launcher_agent_id
    dict_env["SHARED_REPO_MEMORY_PROVIDER_VERSION"] = str_launcher_provider_version
    return dict_env


def _write_subagent_log_header(
    log_file: TextIO,
    *,
    str_action: str,
    str_launcher_agent_id: str,
    str_launcher_provider_version: str,
    cmd: list[str],
) -> None:
    """Write a prefixed header to enrichment.log before launching a subagent.

    Args:
        log_file: Open enrichment log file handle.
        str_action: Short action label such as "checkpoint evaluation" or
            "ADR inspection".
        str_launcher_agent_id: Runtime used to launch the subagent.
        str_launcher_provider_version: Resolved CLI version for that runtime.
        cmd: Full subprocess command that will be executed.

    Returns:
        None: One header line is appended and flushed to the log file.
    """
    str_command_name: str = cmd[0] if cmd else "none"
    str_prefix: str = format_log_prefix(
        str_launcher_agent_id, str_launcher_provider_version
    )
    log_file.write(f"{str_prefix} starting {str_action} via {str_command_name}\n")
    log_file.flush()


def _spawn_checkpoint_evaluation(
    adapter: type,
    context_path: Path,
    repo_root: Path,
) -> bool:
    """Fire-and-forget a subagent to evaluate one episode checkpoint bundle.

    Loads the memory-checkpointer skill and spawns the subagent via the
    adapter's CLI. Falls back to ClaudeAdapter when the adapter cannot spawn
    subagents.

    Args:
        adapter: The detected runtime adapter class.
        context_path: Absolute path to the checkpoint context JSON file.
        repo_root: Absolute path to the repository root.

    Returns:
        bool: True if a subprocess was launched, False if skipped.
    """
    skill_path: Path = (
        Path.home() / ".agent" / "skills" / "memory-checkpointer" / "SKILL.md"
    )
    if not skill_path.exists():
        warn("memory-checkpointer skill not installed; skipping checkpoint evaluation")
        return False

    skill_content: str = skill_path.read_text(encoding="utf-8")
    task: str = (
        "Evaluate the episode checkpoint bundle using context at: " f"{context_path}"
    )
    (
        cmd,
        str_launcher_agent_id,
        str_launcher_provider_version,
    ) = _resolve_bootstrap_command(adapter, skill_content, task, repo_root)
    if cmd is None:
        return False

    log_file: TextIO = _open_enrichment_log(repo_root)
    try:
        _write_subagent_log_header(
            log_file,
            str_action="checkpoint evaluation",
            str_launcher_agent_id=str_launcher_agent_id,
            str_launcher_provider_version=str_launcher_provider_version,
            cmd=cmd,
        )
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=log_file,
            stderr=log_file,
            env=_subagent_env(str_launcher_agent_id, str_launcher_provider_version),
            start_new_session=True,
        )
        return True
    except OSError:
        warn(
            f"checkpoint evaluation subagent launch failed for {str_launcher_agent_id}"
        )
        return False
    finally:
        log_file.close()


def _spawn_adr_inspection(
    adapter: type,
    design_doc_paths: list[str],
    repo_root: Path,
) -> bool:
    """Fire-and-forget a subagent to inspect design docs for ADR-worthy decisions.

    Loads the adr-inspector skill and spawns the subagent via the adapter's CLI.

    Args:
        adapter: The detected runtime adapter class.
        design_doc_paths: Repo-relative paths to changed design documents.
        repo_root: Absolute path to the repository root.

    Returns:
        bool: True if a subprocess was launched, False if skipped.
    """
    skill_path: Path = Path.home() / ".agent" / "skills" / "adr-inspector" / "SKILL.md"
    if not skill_path.exists():
        warn("adr-inspector skill not installed; skipping design doc inspection")
        return False

    skill_content: str = skill_path.read_text(encoding="utf-8")
    doc_list: str = "\n  ".join(design_doc_paths)
    task: str = (
        f"Inspect these changed design docs for ADR-worthy decisions:\n"
        f"  {doc_list}\n"
        f"Repo root: {repo_root}"
    )

    (
        cmd,
        str_launcher_agent_id,
        str_launcher_provider_version,
    ) = _resolve_bootstrap_command(adapter, skill_content, task, repo_root)
    if cmd is None:
        return False

    log_file: TextIO = _open_enrichment_log(repo_root)
    try:
        _write_subagent_log_header(
            log_file,
            str_action="ADR inspection",
            str_launcher_agent_id=str_launcher_agent_id,
            str_launcher_provider_version=str_launcher_provider_version,
            cmd=cmd,
        )
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=log_file,
            stderr=log_file,
            env=_subagent_env(str_launcher_agent_id, str_launcher_provider_version),
            start_new_session=True,
        )
        return True
    except OSError:
        warn(f"ADR inspection subagent launch failed for {str_launcher_agent_id}")
        return False
    finally:
        log_file.close()


def _emit(adapter: type, status: str, message: str = "", **extra: object) -> None:
    """Print a hook response JSON payload using the given adapter.

    Args:
        adapter: The detected adapter class.
        status: Short status token: "ok", "noop", "error", "skipped".
        message: Optional human-readable description.
        **extra: Additional key-value pairs merged into the response.
    """
    filtered = {k: v for k, v in extra.items() if v is not None}
    print(
        adapter.render_hook_response(
            HookResponse(status=status, message=message, extra=filtered)
        )
    )


def main() -> int:
    """Post-turn hook entry point.

    Reads the hook payload from stdin, evaluates whether the turn changed repo
    files, writes a pending capture if so, and optionally spawns async
    publication work from the active episode cluster.

    Returns:
        int: 0 on success or graceful noop; 1 on hard error.
    """
    args = parse_args()
    set_runtime_log_context(detect_adapter().agent_id())
    payload_text = sys.stdin.read()
    try:
        payload = json.loads(payload_text or "{}")
    except json.JSONDecodeError as error:
        warn(f"invalid notify payload JSON: {error}")
        # Adapter detection requires the payload; fall back to env-based detection.
        adapter = detect_adapter()
        _emit(adapter, "error", message="invalid JSON payload")
        return 1

    # Detect the adapter from the hook event in the payload.
    hook_event = find_first(payload, {"hook_event_name", "hookEventName"}) or ""
    adapter = detect_adapter_from_hook_event(hook_event)
    set_runtime_log_context(adapter.agent_id())

    # Normalize the payload into a canonical request.
    req = adapter.normalize_hook_request(payload)

    # Claude Code injects the working directory into the payload as "cwd".
    # Prefer that over os.getcwd() so the hook operates on the correct repo when
    # Claude Code changes directory during a session.
    cwd_override = req.cwd or args.repo_root
    repo_root = try_repo_root(cwd_override)
    if repo_root is None:
        _emit(
            adapter,
            "noop",
            message="current working directory is not inside a Git repository",
        )
        return 0

    append_hook_trace("Notify", "started", repo_root=repo_root)

    # Canonical memory directory must exist; it is created by bootstrap-repo.py
    # which SessionStart calls on every session open.
    if not (repo_root / ".agents" / "memory").is_dir():
        append_hook_trace(
            "Notify",
            "error",
            repo_root=repo_root,
            details={"reason": "missing_agents_memory_dir"},
        )
        warn(
            "missing .agents/memory/; run bootstrap-repo.py or re-open Claude to trigger SessionStart"
        )
        _emit(
            adapter,
            "error",
            message="missing .agents/memory/ directory; repo not bootstrapped",
        )
        return 1

    # Collect repo-grounded evidence and metadata for the current turn.
    strings = flatten_strings(payload)
    files_touched = changed_repo_files(repo_root)
    # File-changing turn gate: a capture is ONLY written when repo files changed.
    # Decision keyword matches alone are insufficient -- every discussion of this
    # system's own design would match, producing shards with no real content.
    if not files_touched:
        append_hook_trace(
            "Notify", "noop", repo_root=repo_root, details={"reason": "not_meaningful"}
        )
        _emit(
            adapter,
            "noop",
            message="notify payload was not meaningful; no shard written",
        )
        return 0

    # Build shard identity fields from the normalised request.
    # Fall back to stable hash-based identifiers when the payload lacks explicit IDs.
    str_thread_identifier: str = req.thread_id or stable_identifier("thread", payload)
    thread_id = _normalize_identifier_component(str_thread_identifier, "thread")
    if not thread_id:
        thread_id = stable_identifier("thread", payload)
    model = adapter.resolve_model(payload)
    branch = current_branch(repo_root)
    workstream_id, workstream_scope = _workstream_identity(
        thread_id if req.thread_id else "", branch
    )

    # Diff-hash deduplication gate: git status is sticky -- once a file is
    # modified it appears in every subsequent turn until committed.  Hash the
    # actual diff content so we only write a new shard when the working-tree
    # content has genuinely changed since the last captured shard for this workstream.
    current_diff_hash = _diff_hash(repo_root, files_touched)
    if _already_captured(repo_root, workstream_id, current_diff_hash):
        append_hook_trace(
            "Notify",
            "noop",
            repo_root=repo_root,
            details={"reason": "diff_unchanged_since_last_shard"},
        )
        _emit(
            adapter,
            "noop",
            message="diff unchanged since last shard for this workstream; skipping duplicate",
        )
        return 0

    now = utc_now()
    timestamp = utc_timestamp(now)
    author = author_slug(repo_root)

    # Exclude volatile fields from the turn hash so the same logical turn
    # produces the same turn_id even if the payload timestamp changes between retries.
    volatile_keys = {
        "timestamp",
        "hook_event_name",
        "stop_hook_active",
        "hookEventName",
    }
    payload_for_turn_hash = {k: v for k, v in payload.items() if k not in volatile_keys}
    str_turn_identifier: str = req.turn_id or stable_identifier(
        "turn", payload_for_turn_hash
    )
    turn_id = _normalize_identifier_component(str_turn_identifier, "turn")
    if not turn_id:
        turn_id = stable_identifier("turn", payload_for_turn_hash)

    diff_summary = _diff_summary(repo_root, files_touched)
    design_docs = [path for path in files_touched if _is_design_doc(path)]
    why_lines = [
        "- Pending episode capture only. Durable memory may publish later if related captures form a trustworthy checkpoint.",
    ]
    what_lines = [f"- Touched {path}" for path in files_touched] or [
        "- No repo files were detected."
    ]
    evidence_lines: list[str] = []
    if diff_summary:
        evidence_lines.append(f"- git diff: {diff_summary}")
    for str_design_doc in design_docs:
        evidence_lines.append(f"- design doc touched: {str_design_doc}")
    if not evidence_lines:
        evidence_lines = ["- Repo changes were detected in the working tree."]
    next_lines = [
        "- Await background episode evaluation before publishing durable memory."
    ]

    # Scan the payload for any ADR cross-references so we can link them in the shard.
    related_adrs = sorted(
        set(re.findall(r"\bADR-\d{4}\b", "\n".join(strings), re.IGNORECASE))
    )

    # Determine stable pending and published paths for this thread+turn.
    path_existing_artifact: Path | None = find_existing_turn_artifact(
        repo_root, thread_id, turn_id
    )
    if path_existing_artifact is not None:
        timestamp = parse_timestamp_from_shard_name(path_existing_artifact.name)
        str_basename: str = path_existing_artifact.stem
    else:
        str_basename = (
            f"{timestamp.replace(':', '-')}"
            f"--{author}--thread_{thread_id}--turn_{turn_id}"
        )

    path_pending_shard: Path = pending_shard_path(repo_root, timestamp, str_basename)
    path_published_shard: Path = published_shard_path(
        repo_root, timestamp, str_basename
    )

    # Assign agent attribution from the detected adapter.
    attribution = adapter.shard_attribution()
    ai_tool = attribution.ai_tool
    ai_surface = attribution.ai_surface
    model = model or attribution.default_model

    # Build the shard frontmatter.  OrderedDict preserves a stable field order
    # that is easier to scan in a Markdown viewer.
    metadata = OrderedDict(
        [
            ("timestamp", timestamp),
            ("author", author),
            ("branch", branch),
            ("thread_id", thread_id),
            ("turn_id", turn_id),
            ("workstream_id", workstream_id),
            ("workstream_scope", workstream_scope),
            ("decision_candidate", False),
            ("enriched", False),
            ("ai_generated", True),
            ("ai_model", model),
            ("ai_tool", ai_tool),
            ("ai_surface", ai_surface),
            ("ai_executor", "local-agent"),
            ("related_adrs", related_adrs),
            ("files_touched", files_touched),
            ("design_docs_touched", design_docs),
            ("diff_summary", diff_summary),
            ("verification", [line.removeprefix("- ") for line in evidence_lines]),
        ]
    )
    body_lines = [
        render_frontmatter(metadata),
        "",
        "## Why",
        "",
        *why_lines,
        "",
        "## What changed",
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
    write_text(path_pending_shard, "\n".join(body_lines))

    # Persist the diff hash so subsequent turns can detect unchanged diffs and
    # skip writing duplicate pending shards for the same working-tree state.
    _save_diff_state(repo_root, workstream_id, current_diff_hash)

    dict_episode_manifest: dict[str, object] | None = None
    path_episode_manifest: Path | None = None
    str_episode_id: str = ""
    str_episode_scope: str = ""
    int_episode_member_count: int = 0
    list_str_episode_pending_paths: list[str] = []
    list_dict_bundle_entries: list[dict[str, object]] = []
    try:
        dict_episode_manifest = rebuild_episode_graph(repo_root, path_pending_shard)
        str_episode_id = str(dict_episode_manifest.get("episode_id", "")).strip()
        str_episode_scope = str(dict_episode_manifest.get("episode_scope", "")).strip()
        int_episode_member_count = int(dict_episode_manifest.get("member_count", 0))
        str_episode_manifest_path: str = str(
            dict_episode_manifest.get("manifest_path", "")
        ).strip()
        if str_episode_manifest_path:
            path_episode_manifest = Path(str_episode_manifest_path)
        (
            list_str_episode_pending_paths,
            list_dict_bundle_entries,
        ) = _episode_bundle_entries(dict_episode_manifest)
    except (OSError, ValueError) as error:
        warn(f"failed to rebuild episode graph: {error}")

    _write_local_notify_metadata(
        repo_root,
        adapter=adapter,
        req=req,
        files_touched=files_touched,
        design_docs_touched=design_docs,
        pending_shard_path=path_pending_shard,
        published_shard_path=path_published_shard,
        workstream_id=workstream_id,
        workstream_scope=workstream_scope,
        episode_id=str_episode_id,
        episode_scope=str_episode_scope,
        episode_manifest_path=path_episode_manifest,
        episode_member_count=int_episode_member_count,
    )

    # --- Async Phase 2: checkpoint evaluation via subagent ---
    # The checkpoint context is local-only and excludes raw prompt or assistant
    # text. Durable memory publishes only if the background evaluation passes
    # the checkpoint validator.
    bool_checkpoint_spawned: bool = False
    if (
        path_episode_manifest is not None
        and list_str_episode_pending_paths
        and list_dict_bundle_entries
    ):
        list_str_secondary_episode_ids: list[str] = []
        list_str_episode_primary_subsystem_hints: list[str] = []
        list_dict_episode_cluster_edges: list[dict[str, object]] = []
        if dict_episode_manifest is not None:
            object_secondary_episode_ids: object = dict_episode_manifest.get(
                "secondary_candidate_episode_ids", []
            )
            if isinstance(object_secondary_episode_ids, list):
                list_str_secondary_episode_ids = [
                    str(str_item).strip()
                    for str_item in object_secondary_episode_ids
                    if str(str_item).strip()
                ]

            object_primary_subsystem_hints: object = dict_episode_manifest.get(
                "primary_subsystem_hints", []
            )
            if isinstance(object_primary_subsystem_hints, list):
                list_str_episode_primary_subsystem_hints = [
                    str(str_item).strip()
                    for str_item in object_primary_subsystem_hints
                    if str(str_item).strip()
                ]

            object_cluster_edges: object = dict_episode_manifest.get(
                "cluster_edges", []
            )
            if isinstance(object_cluster_edges, list):
                list_dict_episode_cluster_edges = [
                    dict(object_edge)
                    for object_edge in object_cluster_edges
                    if isinstance(object_edge, dict)
                ]

        context_data: dict[str, object] = {
            "repo_root": str(repo_root),
            "current_pending_shard": str(path_pending_shard),
            "pending_shard_paths": list_str_episode_pending_paths,
            "pending_bundle": list_dict_bundle_entries,
            "published_shard_path": str(path_published_shard),
            "workstream_id": workstream_id,
            "workstream_scope": workstream_scope,
            "episode_manifest_path": str(path_episode_manifest),
            "episode_id": str_episode_id,
            "episode_scope": str_episode_scope,
            "episode_status": (
                str(dict_episode_manifest.get("status", "")).strip()
                if dict_episode_manifest is not None
                else ""
            ),
            "episode_member_count": int_episode_member_count,
            "secondary_candidate_episode_ids": list_str_secondary_episode_ids,
            "episode_primary_subsystem_hints": list_str_episode_primary_subsystem_hints,
            "episode_cluster_edges": list_dict_episode_cluster_edges,
            "branch": branch,
            "files_touched": files_touched,
            "design_docs_touched": design_docs,
            "diff_summary": diff_summary,
            "adr_index_path": str(
                repo_root / ".agents" / "memory" / "adr" / "INDEX.md"
            ),
            "recent_summary_paths": _recent_summary_paths(repo_root),
        }
        context_filename: str = f".checkpoint-{turn_id}.json"
        path_context_dir: Path = _checkpoint_context_dir(repo_root)
        path_context: Path = path_context_dir / context_filename
        try:
            write_text(
                path_context, json.dumps(context_data, indent=2, sort_keys=True) + "\n"
            )
            bool_checkpoint_spawned = _spawn_checkpoint_evaluation(
                adapter, path_context, repo_root
            )
            if bool_checkpoint_spawned:
                info(
                    f"spawned checkpoint evaluation subagent for {path_published_shard.name}"
                )
            elif path_context.exists():
                path_context.unlink(missing_ok=True)
        except OSError as error:
            warn(f"failed to write checkpoint context: {error}")
    else:
        warn(
            "skipping checkpoint evaluation because the active episode cluster could not be derived"
        )

    # --- Async Phase 2b: design doc ADR inspection ---
    # When the turn touched design docs, spawn a separate subagent to inspect
    # them for ADR-worthy decisions. Independent of checkpoint publication.
    bool_inspection_spawned: bool = False
    if design_docs:
        bool_inspection_spawned = _spawn_adr_inspection(adapter, design_docs, repo_root)
        if bool_inspection_spawned:
            info(
                f"spawned ADR inspection subagent for {len(design_docs)} design doc(s)"
            )

    append_hook_trace(
        "Notify",
        "success",
        repo_root=repo_root,
        details={
            "files_touched": files_touched,
            "pending_shard_path": str(path_pending_shard.relative_to(repo_root)),
            "published_shard_path": str(path_published_shard.relative_to(repo_root)),
            "thread_id": thread_id,
            "turn_id": turn_id,
            "workstream_id": workstream_id,
            "workstream_scope": workstream_scope,
            "episode_id": str_episode_id,
            "episode_scope": str_episode_scope,
            "episode_member_count": int_episode_member_count,
            "episode_manifest_path": (
                str(path_episode_manifest.relative_to(repo_root))
                if path_episode_manifest is not None
                else ""
            ),
            "checkpoint_spawned": bool_checkpoint_spawned,
            "adr_inspection_spawned": bool_inspection_spawned,
            "design_docs_touched": design_docs,
        },
    )
    info(f"wrote pending shard {path_pending_shard.relative_to(repo_root)}")
    _emit(
        adapter,
        "ok",
        pending_shard_path=str(path_pending_shard.relative_to(repo_root)),
        published_shard_path=str(path_published_shard.relative_to(repo_root)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "Notify"))
