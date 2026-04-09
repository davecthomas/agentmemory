#!/usr/bin/env python3
"""publish-checkpoint.py -- Validate and publish one durable episode checkpoint.

This script is invoked by the background memory-checkpointer subagent after
post-turn-notify.py writes a pending local-only capture and emits a checkpoint
context manifest. The subagent may either:

  1. Call this script with structured checkpoint fields to publish a durable
     shard, or
  2. Call this script with --skip-publish when the bundle does not justify a
     trustworthy checkpoint.

The script is the final trust boundary for shared repo memory. It validates
that the candidate is episode-level, mechanically distinct from raw diff
restatements, and rich enough to justify publication. When validation fails,
the script leaves pending captures in place and publishes nothing.

Usage:
  publish-checkpoint.py <context-json-path> --skip-publish [--reason "..."]

  publish-checkpoint.py <context-json-path> \
      --workstream-goal "..." \
      --subsystem-surface "..." \
      --turn-outcome "..." \
      --why "..." \
      --what-changed "..." \
      --evidence "..." \
      --next "..." \
      --source-pending-shard /abs/path/to/pending.md \
      [--source-pending-shard /abs/path/to/another.md] \
      [--decision-candidate]

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/publish-checkpoint.py
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common import (
    info,
    parse_frontmatter,
    render_frontmatter,
    render_sections,
    safe_main,
    stage_paths,
    warn,
    write_text,
)

_PLACEHOLDER_PHRASES: tuple[str, ...] = (
    "pending workstream capture",
    "pending episode capture",
    "await checkpoint evaluation",
    "review the generated shard",
    "repo state changed during this agent turn",
    "no content provided",
    "raw shard",
    "raw fixture",
    "pending raw shard",
    "generated shard",
    "capture only",
)
_MECHANICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d+\s+files?\s+changed\b", re.IGNORECASE),
    re.compile(r"\binsertions?\(\+\)", re.IGNORECASE),
    re.compile(r"\bdeletions?\(-\)", re.IGNORECASE),
    re.compile(r"\bgit diff\b", re.IGNORECASE),
    re.compile(r"\bupdated\s+[\w./-]+\.[A-Za-z0-9]+\b", re.IGNORECASE),
    re.compile(r"\bcreated\s+[\w./-]+\.[A-Za-z0-9]+\b", re.IGNORECASE),
    re.compile(r"\bmodified\s+[\w./-]+\.[A-Za-z0-9]+\b", re.IGNORECASE),
)
_FILE_LIKE_PATTERN: re.Pattern[str] = re.compile(r"[\w./-]+\.[A-Za-z0-9]+")
_MEANINGFUL_TOKEN_STOPWORDS: set[str] = {
    "about",
    "after",
    "before",
    "branch",
    "built",
    "code",
    "from",
    "into",
    "memory",
    "repo",
    "shared",
    "that",
    "this",
    "with",
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for checkpoint publication.

    Returns:
        argparse.Namespace: Parsed arguments containing the checkpoint context
            path, publication fields, and optional no-publish controls.
    """
    argument_parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Validate and publish one shared-memory episode checkpoint."
    )
    argument_parser.add_argument(
        "context_path",
        help="Path to the checkpoint context JSON file.",
    )
    argument_parser.add_argument(
        "--skip-publish",
        action="store_true",
        default=False,
        help="Clean up the context file without publishing any durable shard.",
    )
    argument_parser.add_argument(
        "--reason",
        default="",
        help="Optional no-publish reason recorded in stderr logs only.",
    )
    argument_parser.add_argument(
        "--workstream-goal",
        default="",
        help="Broader issue or goal being advanced by the workstream.",
    )
    argument_parser.add_argument(
        "--subsystem-surface",
        default="",
        help="Subsystem or architectural surface affected by the workstream.",
    )
    argument_parser.add_argument(
        "--turn-outcome",
        default="",
        help="Concrete latest-turn outcome inside the broader workstream.",
    )
    argument_parser.add_argument(
        "--why",
        default="",
        help="Why section content for the published checkpoint.",
    )
    argument_parser.add_argument(
        "--what-changed",
        default="",
        help="What changed section content for the published checkpoint.",
    )
    argument_parser.add_argument(
        "--evidence",
        default="",
        help="Evidence section content for the published checkpoint.",
    )
    argument_parser.add_argument(
        "--next",
        default="",
        help="Next section content for the published checkpoint.",
    )
    argument_parser.add_argument(
        "--decision-candidate",
        action="store_true",
        default=False,
        help="Mark the published checkpoint as an ADR decision candidate.",
    )
    argument_parser.add_argument(
        "--source-pending-shard",
        action="append",
        default=[],
        help="Absolute path to one pending capture consumed by this checkpoint.",
    )
    namespace_args: argparse.Namespace = argument_parser.parse_args()
    return namespace_args


def _load_context(path_context: Path) -> dict[str, Any]:
    """Load and validate the checkpoint context JSON.

    Args:
        path_context: Absolute path to the context manifest created by
            post-turn-notify.py.

    Returns:
        dict[str, Any]: Parsed context manifest with the required schema keys.

    Raises:
        SystemExit: Raised when the file is missing, unreadable, or incomplete.
    """
    if not path_context.exists():
        warn(f"checkpoint context not found: {path_context}")
        raise SystemExit(1)

    try:
        dict_context: dict[str, Any] = json.loads(
            path_context.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        warn(f"failed to read checkpoint context: {error}")
        raise SystemExit(1)

    set_required_keys: set[str] = {
        "repo_root",
        "current_pending_shard",
        "pending_shard_paths",
        "published_shard_path",
        "workstream_id",
        "workstream_scope",
    }
    set_missing_keys: set[str] = set_required_keys - set(dict_context.keys())
    if set_missing_keys:
        warn(f"checkpoint context missing required keys: {sorted(set_missing_keys)}")
        raise SystemExit(1)
    return dict_context


def _cleanup_context(path_context: Path) -> None:
    """Delete the ephemeral checkpoint context file when it still exists.

    Args:
        path_context: Absolute path to the local-only context manifest.

    Returns:
        None: Missing files are ignored.
    """
    try:
        path_context.unlink(missing_ok=True)
    except OSError as error:
        warn(f"failed to remove checkpoint context {path_context}: {error}")


def _normalize_text(str_text: str) -> str:
    """Collapse whitespace and lowercase text for heuristic comparisons.

    Args:
        str_text: Raw text value to normalize.

    Returns:
        str: Lowercased single-line representation of the input text.
    """
    str_normalized_text: str = " ".join(str_text.split()).strip().lower()
    return str_normalized_text


def _meaningful_tokens(str_text: str) -> set[str]:
    """Return a reduced set of informative tokens for overlap checks.

    Args:
        str_text: Raw synopsis or section text.

    Returns:
        set[str]: Lowercased tokens with short/common stopwords removed.
    """
    set_tokens: set[str] = set()
    list_str_tokens: list[str] = re.findall(r"[a-z0-9]+", _normalize_text(str_text))
    for str_token in list_str_tokens:
        if len(str_token) < 4:
            continue
        if str_token in _MEANINGFUL_TOKEN_STOPWORDS:
            continue
        set_tokens.add(str_token)
    return set_tokens


def _contains_placeholder_text(str_text: str) -> bool:
    """Return True when text matches known low-signal placeholder phrases.

    Args:
        str_text: Candidate shard text to inspect.

    Returns:
        bool: True when the text contains a known placeholder phrase.
    """
    str_normalized_text: str = _normalize_text(str_text)
    for str_phrase in _PLACEHOLDER_PHRASES:
        if str_phrase in str_normalized_text:
            return True
    return False


def _looks_mechanical(str_text: str) -> bool:
    """Return True when text looks like diff stats or filename bookkeeping.

    Args:
        str_text: Candidate shard text to inspect.

    Returns:
        bool: True when the content appears to be mechanical repo bookkeeping
            rather than durable semantic memory.
    """
    str_normalized_text: str = _normalize_text(str_text)
    for pattern_mechanical in _MECHANICAL_PATTERNS:
        if pattern_mechanical.search(str_normalized_text):
            return True

    list_str_file_like_matches: list[str] = _FILE_LIKE_PATTERN.findall(str_text)
    list_str_tokens: list[str] = re.findall(r"[A-Za-z0-9_.\\/-]+", str_text)
    if list_str_tokens:
        float_file_ratio: float = len(list_str_file_like_matches) / len(list_str_tokens)
        if float_file_ratio >= 0.4:
            return True
    return False


def _sections_are_too_similar(*sequence_str_sections: str) -> bool:
    """Return True when multiple synopsis strings collapse to the same idea.

    Args:
        *sequence_str_sections: One or more normalized prose fields that should
            each add distinct semantic value.

    Returns:
        bool: True when any pair is identical, mostly overlapping, or one is a
            trivial substring of the other.
    """
    list_str_sections: list[str] = [
        section for section in sequence_str_sections if section
    ]
    for int_left_index, str_left_text in enumerate(list_str_sections):
        set_left_tokens: set[str] = _meaningful_tokens(str_left_text)
        str_left_normalized: str = _normalize_text(str_left_text)
        for str_right_text in list_str_sections[int_left_index + 1 :]:
            str_right_normalized: str = _normalize_text(str_right_text)
            if not str_left_normalized or not str_right_normalized:
                continue
            if (
                str_left_normalized == str_right_normalized
                or str_left_normalized in str_right_normalized
                or str_right_normalized in str_left_normalized
            ):
                return True
            set_right_tokens: set[str] = _meaningful_tokens(str_right_text)
            if not set_left_tokens or not set_right_tokens:
                continue
            set_overlap_tokens: set[str] = set_left_tokens & set_right_tokens
            float_overlap_ratio: float = len(set_overlap_tokens) / min(
                len(set_left_tokens), len(set_right_tokens)
            )
            if float_overlap_ratio >= 0.8:
                return True
    return False


def _format_section_lines(str_raw_text: str) -> list[str]:
    """Convert raw section text into bullet-prefixed shard lines.

    Args:
        str_raw_text: Free-form text produced by the background subagent.

    Returns:
        list[str]: Bullet-prefixed non-empty section lines.
    """
    str_stripped_text: str = str_raw_text.strip()
    if not str_stripped_text:
        return []

    list_str_lines: list[str] = [
        str_line.strip()
        for str_line in str_stripped_text.splitlines()
        if str_line.strip()
    ]
    list_str_formatted_lines: list[str] = []
    for str_line in list_str_lines:
        if str_line.startswith("- "):
            list_str_formatted_lines.append(str_line)
        elif str_line.startswith("-"):
            list_str_formatted_lines.append(f"- {str_line.lstrip('-').strip()}")
        else:
            list_str_formatted_lines.append(f"- {str_line}")
    return list_str_formatted_lines


def _load_pending_metadata(path_pending_shard: Path) -> dict[str, Any]:
    """Read one pending capture and return its parsed frontmatter metadata.

    Args:
        path_pending_shard: Absolute path to the pending Markdown capture.

    Returns:
        dict[str, Any]: Parsed frontmatter fields from the pending capture.

    Raises:
        ValueError: Raised when the pending capture lacks valid frontmatter.
    """
    str_pending_text: str = path_pending_shard.read_text(encoding="utf-8")
    dict_metadata: dict[str, Any]
    _body: str
    dict_metadata, _body = parse_frontmatter(str_pending_text)
    return dict_metadata


def _resolve_source_pending_shards(
    dict_context: dict[str, Any], sequence_str_source_paths: Sequence[str]
) -> list[Path]:
    """Validate the requested source pending shards against the context bundle.

    Args:
        dict_context: Parsed checkpoint context manifest.
        sequence_str_source_paths: Source paths received from the subagent CLI.

    Returns:
        list[Path]: Normalized absolute pending-capture paths in deterministic
            order, with duplicates removed.

    Raises:
        ValueError: Raised when the source list is empty, missing the current
            pending capture, or references paths outside the declared bundle.
    """
    set_declared_pending_paths: set[Path] = {
        Path(str(path_value)).resolve()
        for path_value in dict_context.get("pending_shard_paths", [])
    }
    path_current_pending: Path = Path(
        str(dict_context["current_pending_shard"])
    ).resolve()
    list_path_source_shards: list[Path] = []
    set_seen_paths: set[Path] = set()

    for str_source_path in sequence_str_source_paths:
        path_source_shard: Path = Path(str_source_path).resolve()
        if path_source_shard in set_seen_paths:
            continue
        if path_source_shard not in set_declared_pending_paths:
            raise ValueError(
                f"source pending shard is outside the declared bundle: {path_source_shard}"
            )
        set_seen_paths.add(path_source_shard)
        list_path_source_shards.append(path_source_shard)

    if not list_path_source_shards:
        raise ValueError("at least one source pending shard is required")
    if path_current_pending not in set(list_path_source_shards):
        raise ValueError(
            "published checkpoints must include the current pending capture that triggered evaluation"
        )
    return list_path_source_shards


def _flatten_lines(dict_sections: OrderedDict[str, list[str]]) -> list[str]:
    """Return every bullet line across all rendered shard sections.

    Args:
        dict_sections: Ordered section mapping prepared for output rendering.

    Returns:
        list[str]: Flattened list of section lines in declaration order.
    """
    list_str_all_lines: list[str] = []
    for list_str_section_lines in dict_sections.values():
        list_str_all_lines.extend(list_str_section_lines)
    return list_str_all_lines


def _validate_candidate(
    dict_context: dict[str, Any],
    list_path_source_shards: Sequence[Path],
    str_workstream_goal: str,
    str_subsystem_surface: str,
    str_turn_outcome: str,
    dict_sections: OrderedDict[str, list[str]],
    list_dict_source_metadata: Sequence[dict[str, Any]],
) -> list[str]:
    """Return validation failures for a candidate checkpoint publication.

    Args:
        dict_context: Parsed checkpoint context manifest.
        list_path_source_shards: Pending captures the subagent wants to consume.
        str_workstream_goal: Broader workstream goal proposed by the subagent.
        str_subsystem_surface: Affected subsystem or architectural surface.
        str_turn_outcome: Concrete latest-turn outcome inside the workstream.
        dict_sections: Canonical shard sections ready for rendering.
        list_dict_source_metadata: Parsed metadata from the source pending captures.

    Returns:
        list[str]: Human-readable validation failures. An empty list means the
            candidate may be published.
    """
    list_str_failures: list[str] = []
    list_str_synopsis_fields: list[tuple[str, str]] = [
        ("workstream goal", str_workstream_goal),
        ("subsystem surface", str_subsystem_surface),
        ("turn outcome", str_turn_outcome),
    ]

    for str_label, str_value in list_str_synopsis_fields:
        str_normalized_value: str = _normalize_text(str_value)
        if len(str_normalized_value) < 20:
            list_str_failures.append(
                f"{str_label} is too short to carry durable context"
            )
        if _contains_placeholder_text(str_value):
            list_str_failures.append(f"{str_label} contains placeholder text")
        if _looks_mechanical(str_value):
            list_str_failures.append(
                f"{str_label} still looks mechanical or filename-driven"
            )

    if _sections_are_too_similar(
        str_workstream_goal, str_subsystem_surface, str_turn_outcome
    ):
        list_str_failures.append(
            "workstream goal, subsystem surface, and turn outcome are too similar to form a gestalt checkpoint"
        )

    for str_section_name, list_str_section_lines in dict_sections.items():
        if not list_str_section_lines:
            list_str_failures.append(f"{str_section_name} section is empty")
            continue
        str_section_text: str = "\n".join(list_str_section_lines)
        if _contains_placeholder_text(str_section_text):
            list_str_failures.append(f"{str_section_name} contains placeholder text")
        if _looks_mechanical(str_section_text):
            list_str_failures.append(
                f"{str_section_name} still looks like diff stats or filename bookkeeping"
            )

    str_why_text: str = "\n".join(dict_sections["Why"])
    str_what_text: str = "\n".join(dict_sections["What changed"])
    str_evidence_text: str = "\n".join(dict_sections["Evidence"])
    if _sections_are_too_similar(str_why_text, str_what_text, str_evidence_text):
        list_str_failures.append(
            "Why, What changed, and Evidence do not add distinct semantic value"
        )

    list_str_all_lines: list[str] = _flatten_lines(dict_sections)
    if not any(
        token in _normalize_text("\n".join(list_str_all_lines))
        for token in (
            "test",
            "design",
            "adr",
            "summary",
            "hook",
            "validator",
            "publish",
        )
    ):
        list_str_failures.append(
            "candidate lacks grounded evidence such as tests, design docs, ADRs, hooks, or validators"
        )

    str_workstream_scope: str = str(
        dict_context.get("episode_scope", dict_context.get("workstream_scope", ""))
    ).strip()
    int_episode_member_count: int = int(
        dict_context.get("episode_member_count", len(list_path_source_shards))
    )
    bool_has_design_doc_grounding: bool = False
    for dict_source_metadata in list_dict_source_metadata:
        object_design_docs: object = dict_source_metadata.get("design_docs_touched", [])
        list_str_design_docs: list[str] = (
            list(object_design_docs) if isinstance(object_design_docs, list) else []
        )
        if list_str_design_docs:
            bool_has_design_doc_grounding = True
            break
    if (
        str_workstream_scope == "branch"
        and int_episode_member_count < 2
        and not bool_has_design_doc_grounding
    ):
        list_str_failures.append(
            "branch-scoped single-capture checkpoints require either multiple related captures or design-doc grounding"
        )

    return list_str_failures


def _deduplicate_string_lists(sequence_str_values: Sequence[str]) -> list[str]:
    """Return a stable deduplicated list of non-empty string values.

    Args:
        sequence_str_values: Arbitrary ordered string values.

    Returns:
        list[str]: Deduplicated strings preserving first-seen order.
    """
    list_str_deduplicated_values: list[str] = []
    set_seen_values: set[str] = set()
    for str_value in sequence_str_values:
        str_clean_value: str = str(str_value).strip()
        if not str_clean_value or str_clean_value in set_seen_values:
            continue
        set_seen_values.add(str_clean_value)
        list_str_deduplicated_values.append(str_clean_value)
    return list_str_deduplicated_values


def _build_published_metadata(
    list_dict_source_metadata: Sequence[dict[str, Any]],
    list_path_source_shards: Sequence[Path],
    dict_context: dict[str, Any],
    str_workstream_goal: str,
    str_subsystem_surface: str,
    str_turn_outcome: str,
    bool_decision_candidate: bool,
    path_repo_root: Path,
) -> OrderedDict[str, Any]:
    """Construct the frontmatter for one published checkpoint shard.

    Args:
        list_dict_source_metadata: Parsed metadata from each source pending capture.
        list_path_source_shards: Absolute pending-capture paths consumed here.
        dict_context: Parsed checkpoint context manifest for the active episode.
        str_workstream_goal: Approved broader workstream goal.
        str_subsystem_surface: Approved subsystem or architectural surface.
        str_turn_outcome: Approved concrete latest-turn outcome.
        bool_decision_candidate: Whether the checkpoint should enter the ADR flow.
        path_repo_root: Absolute repository root used to relativize source paths.

    Returns:
        OrderedDict[str, Any]: Stable ordered frontmatter for the durable shard.
    """
    dict_latest_metadata: dict[str, Any] = dict(list_dict_source_metadata[-1])
    list_str_files_touched: list[str] = []
    list_str_related_adrs: list[str] = []
    list_str_verification: list[str] = []
    list_str_design_docs_touched: list[str] = []
    list_str_source_pending_paths: list[str] = []

    for path_source_shard, dict_source_metadata in zip(
        list_path_source_shards, list_dict_source_metadata, strict=True
    ):
        object_files_touched: object = dict_source_metadata.get("files_touched", [])
        list_str_files_touched.extend(
            str(item)
            for item in object_files_touched
            if isinstance(object_files_touched, list)
        )
        object_related_adrs: object = dict_source_metadata.get("related_adrs", [])
        list_str_related_adrs.extend(
            str(item)
            for item in object_related_adrs
            if isinstance(object_related_adrs, list)
        )
        object_verification: object = dict_source_metadata.get("verification", [])
        list_str_verification.extend(
            str(item)
            for item in object_verification
            if isinstance(object_verification, list)
        )
        object_design_docs: object = dict_source_metadata.get("design_docs_touched", [])
        list_str_design_docs_touched.extend(
            str(item)
            for item in object_design_docs
            if isinstance(object_design_docs, list)
        )
        list_str_source_pending_paths.append(
            str(path_source_shard.relative_to(path_repo_root))
        )

    ordered_metadata: OrderedDict[str, Any] = OrderedDict(
        [
            ("timestamp", str(dict_latest_metadata.get("timestamp", ""))),
            ("author", str(dict_latest_metadata.get("author", "unknown"))),
            ("branch", str(dict_latest_metadata.get("branch", "HEAD"))),
            ("thread_id", str(dict_latest_metadata.get("thread_id", ""))),
            ("turn_id", str(dict_latest_metadata.get("turn_id", ""))),
            ("workstream_id", str(dict_latest_metadata.get("workstream_id", ""))),
            ("workstream_scope", str(dict_latest_metadata.get("workstream_scope", ""))),
            ("episode_id", str(dict_context.get("episode_id", ""))),
            ("episode_scope", str(dict_context.get("episode_scope", ""))),
            ("checkpoint_goal", str_workstream_goal.strip()),
            ("checkpoint_surface", str_subsystem_surface.strip()),
            ("checkpoint_outcome", str_turn_outcome.strip()),
            ("decision_candidate", bool_decision_candidate),
            ("enriched", True),
            ("ai_generated", bool(dict_latest_metadata.get("ai_generated", True))),
            ("ai_model", str(dict_latest_metadata.get("ai_model", "unknown"))),
            ("ai_tool", str(dict_latest_metadata.get("ai_tool", "unknown"))),
            ("ai_surface", str(dict_latest_metadata.get("ai_surface", "unknown"))),
            (
                "ai_executor",
                str(dict_latest_metadata.get("ai_executor", "local-agent")),
            ),
            (
                "related_adrs",
                _deduplicate_string_lists(sorted(list_str_related_adrs)),
            ),
            (
                "files_touched",
                _deduplicate_string_lists(sorted(list_str_files_touched)),
            ),
            (
                "design_docs_touched",
                _deduplicate_string_lists(sorted(list_str_design_docs_touched)),
            ),
            ("verification", _deduplicate_string_lists(list_str_verification)),
            ("source_pending_shards", list_str_source_pending_paths),
        ]
    )
    return ordered_metadata


def _summary_date_from_published_path(path_published_shard: Path) -> str:
    """Return the `YYYY-MM-DD` directory name for one published checkpoint shard.

    Args:
        path_published_shard: Absolute path under `.agents/memory/daily/<date>/events/`.

    Returns:
        str: Summary date directory name extracted from the published path.

    Raises:
        ValueError: Raised when the path is not under the canonical daily layout.
    """
    list_str_path_parts: list[str] = list(path_published_shard.parts)
    if "daily" not in list_str_path_parts:
        raise ValueError(
            f"published shard path is outside the daily tree: {path_published_shard}"
        )
    int_daily_index: int = (
        len(list_str_path_parts) - 1 - list_str_path_parts[::-1].index("daily")
    )
    if int_daily_index + 2 >= len(list_str_path_parts):
        raise ValueError(f"published shard path is incomplete: {path_published_shard}")
    str_date_dir: str = list_str_path_parts[int_daily_index + 1]
    str_next_component: str = list_str_path_parts[int_daily_index + 2]
    if str_next_component != "events":
        raise ValueError(
            f"published shard path is outside the events directory: {path_published_shard}"
        )
    return str_date_dir


def _rebuild_summary(path_repo_root: Path, str_summary_date: str) -> None:
    """Rebuild the daily summary for one published checkpoint date.

    Args:
        path_repo_root: Absolute repository root.
        str_summary_date: Date directory whose summary should be regenerated.

    Returns:
        None: Raises CalledProcessError on rebuild failures.
    """
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("rebuild-summary.py")),
            "--repo-root",
            str(path_repo_root),
            "--date",
            str_summary_date,
        ],
        cwd=str(path_repo_root),
        check=True,
        capture_output=True,
        text=True,
    )


def _publish_checkpoint(
    dict_context: dict[str, Any],
    list_path_source_shards: Sequence[Path],
    ordered_metadata: OrderedDict[str, Any],
    dict_sections: OrderedDict[str, list[str]],
    path_context: Path,
) -> int:
    """Write the durable checkpoint shard, rebuild summary, stage, and clean up.

    Args:
        dict_context: Parsed checkpoint context manifest.
        list_path_source_shards: Source pending captures to delete on success.
        ordered_metadata: Final frontmatter metadata for the published shard.
        dict_sections: Final body sections for the published shard.
        path_context: Absolute path to the ephemeral checkpoint context file.

    Returns:
        int: Zero on success, nonzero on failure.
    """
    path_repo_root: Path = Path(str(dict_context["repo_root"])).resolve()
    path_published_shard: Path = Path(
        str(dict_context["published_shard_path"])
    ).resolve()
    str_summary_date: str
    try:
        str_summary_date = _summary_date_from_published_path(path_published_shard)
    except ValueError as error:
        warn(str(error))
        return 1

    str_shard_text: str = (
        render_frontmatter(ordered_metadata) + "\n\n" + render_sections(dict_sections)
    )
    write_text(path_published_shard, str_shard_text)
    info(f"published {path_published_shard.relative_to(path_repo_root)}")

    try:
        _rebuild_summary(path_repo_root, str_summary_date)
    except subprocess.CalledProcessError as error:
        warn(f"summary rebuild after checkpoint publish failed: {error.stderr[:200]}")
        return 1

    path_summary: Path = (
        path_repo_root
        / ".agents"
        / "memory"
        / "daily"
        / str_summary_date
        / "summary.md"
    )
    list_path_stage_paths: list[Path] = [path_published_shard]
    if path_summary.exists():
        list_path_stage_paths.append(path_summary)
    stage_paths(path_repo_root, list_path_stage_paths)

    for path_source_shard in list_path_source_shards:
        try:
            path_source_shard.unlink()
        except OSError as error:
            warn(
                f"failed to delete consumed pending shard {path_source_shard}: {error}"
            )
    _cleanup_context(path_context)
    return 0


def main() -> int:
    """Validate and publish one episode checkpoint when the candidate is trustworthy.

    Returns:
        int: Zero on successful publish or intentional no-publish cleanup, or a
            nonzero value when validation fails or the context is invalid.
    """
    namespace_args: argparse.Namespace = parse_args()
    path_context: Path = Path(namespace_args.context_path).resolve()
    dict_context: dict[str, Any] = _load_context(path_context)

    if namespace_args.skip_publish:
        str_reason: str = namespace_args.reason.strip()
        if str_reason:
            info(f"checkpoint evaluation skipped publish: {str_reason}")
        _cleanup_context(path_context)
        return 0

    try:
        list_path_source_shards: list[Path] = _resolve_source_pending_shards(
            dict_context, namespace_args.source_pending_shard
        )
    except ValueError as error:
        warn(str(error))
        return 1

    for path_source_shard in list_path_source_shards:
        if not path_source_shard.exists():
            warn(f"source pending shard no longer exists: {path_source_shard}")
            return 1

    list_dict_source_metadata: list[dict[str, Any]] = []
    for path_source_shard in list_path_source_shards:
        try:
            dict_source_metadata: dict[str, Any] = _load_pending_metadata(
                path_source_shard
            )
        except ValueError:
            warn(f"pending shard has invalid frontmatter: {path_source_shard}")
            return 1
        list_dict_source_metadata.append(dict_source_metadata)

    ordered_sections: OrderedDict[str, list[str]] = OrderedDict(
        [
            ("Why", _format_section_lines(namespace_args.why)),
            ("What changed", _format_section_lines(namespace_args.what_changed)),
            ("Evidence", _format_section_lines(namespace_args.evidence)),
            ("Next", _format_section_lines(namespace_args.next)),
        ]
    )
    list_str_validation_failures: list[str] = _validate_candidate(
        dict_context,
        list_path_source_shards,
        namespace_args.workstream_goal,
        namespace_args.subsystem_surface,
        namespace_args.turn_outcome,
        ordered_sections,
        list_dict_source_metadata,
    )
    if list_str_validation_failures:
        for str_failure in list_str_validation_failures:
            warn(f"checkpoint publish rejected: {str_failure}")
        return 1

    path_repo_root: Path = Path(str(dict_context["repo_root"])).resolve()
    ordered_metadata: OrderedDict[str, Any] = _build_published_metadata(
        list_dict_source_metadata,
        list_path_source_shards,
        dict_context,
        namespace_args.workstream_goal,
        namespace_args.subsystem_surface,
        namespace_args.turn_outcome,
        namespace_args.decision_candidate,
        path_repo_root,
    )
    int_result: int = _publish_checkpoint(
        dict_context,
        list_path_source_shards,
        ordered_metadata,
        ordered_sections,
        path_context,
    )
    return int_result


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "PublishCheckpoint"))
