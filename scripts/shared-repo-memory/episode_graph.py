#!/usr/bin/env python3
"""episode_graph.py -- Deterministic local episode-graph clustering for pending captures.

This helper builds a bounded, privacy-safe local graph from pending capture
metadata under `.agents/memory/pending/`. Each pending capture is treated as a
graph node, weighted edges are scored from repo-grounded signals, and connected
components above the primary threshold become candidate episode clusters.

The graph and cluster manifests are local-only derived state written under
`.agents/memory/state/episode-graph/episodes/`. They are not durable shared
memory and must never be committed.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import (
    EPISODE_MANIFESTS_RELATIVE_DIR,
    PENDING_SHARDS_RELATIVE_DIR,
    ensure_dir,
    parse_frontmatter,
    slugify,
    write_text,
)

_ISSUE_ID_PATTERN: re.Pattern[str] = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_MAX_GRAPH_PENDING_CAPTURES: int = 48
_PRIMARY_EDGE_THRESHOLD: int = 8
_SECONDARY_EDGE_THRESHOLD: int = 5


def episode_manifest_dir(repo_root: Path) -> Path:
    """Return the local episode-manifest directory, creating it if needed.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Path: Absolute path to `.agents/memory/state/episode-graph/episodes/`.
    """
    path_manifest_dir: Path = ensure_dir(repo_root / EPISODE_MANIFESTS_RELATIVE_DIR)
    return path_manifest_dir


def _pending_capture_paths(repo_root: Path, *, limit: int) -> list[Path]:
    """Return a bounded chronological list of pending capture files.

    Args:
        repo_root: Absolute path to the repository root.
        limit: Maximum number of pending captures to consider while building the
            local episode graph.

    Returns:
        list[Path]: Oldest-first pending capture paths, bounded to the newest
            `limit` captures.
    """
    path_pending_root: Path = repo_root / PENDING_SHARDS_RELATIVE_DIR
    list_path_pending_shards: list[Path] = sorted(path_pending_root.glob("*/*.md"))
    if len(list_path_pending_shards) > limit:
        list_path_pending_shards = list_path_pending_shards[-limit:]
    return list_path_pending_shards


def _path_scope_keys(list_str_paths: Sequence[str]) -> list[str]:
    """Return coarse subsystem scope keys for touched repo paths.

    Args:
        list_str_paths: Repo-relative paths touched by one pending capture.

    Returns:
        list[str]: Sorted top-level or top-two-level path keys used to compare
            likely subsystem overlap between captures.
    """
    set_str_scope_keys: set[str] = set()
    str_path: str
    for str_path in list_str_paths:
        path_item: Path = Path(str_path)
        tuple_str_parts: tuple[str, ...] = path_item.parts
        if not tuple_str_parts:
            continue
        if len(tuple_str_parts) == 1:
            set_str_scope_keys.add(tuple_str_parts[0])
            continue
        set_str_scope_keys.add("/".join(tuple_str_parts[:2]))
    list_str_scope_keys: list[str] = sorted(set_str_scope_keys)
    return list_str_scope_keys


def _issue_ids_for_values(list_str_values: Sequence[str]) -> list[str]:
    """Extract stable issue identifiers from a sequence of raw text values.

    Args:
        list_str_values: Raw strings such as branch names, diff summaries, or
            file paths that may contain identifiers like `AIEN-127`.

    Returns:
        list[str]: Sorted unique issue identifiers discovered in the input.
    """
    set_str_issue_ids: set[str] = set()
    str_value: str
    for str_value in list_str_values:
        for str_issue_id in _ISSUE_ID_PATTERN.findall(str_value):
            set_str_issue_ids.add(str_issue_id)
    list_str_issue_ids: list[str] = sorted(set_str_issue_ids)
    return list_str_issue_ids


def _validation_signals(list_str_paths: Sequence[str]) -> list[str]:
    """Return paths that look like tests, validators, or hooks.

    Args:
        list_str_paths: Repo-relative paths touched by one pending capture.

    Returns:
        list[str]: Sorted subset of input paths that likely carry validation or
            hook-closing-loop meaning for episode association.
    """
    list_str_matches: list[str] = []
    str_path: str
    for str_path in list_str_paths:
        str_lower_path: str = str_path.lower()
        if any(
            str_keyword in str_lower_path
            for str_keyword in ("test", "spec", "validator", "hook")
        ):
            list_str_matches.append(str_path)
    list_str_unique_matches: list[str] = sorted(dict.fromkeys(list_str_matches))
    return list_str_unique_matches


def _parse_timestamp(str_timestamp: str) -> datetime | None:
    """Parse one ISO-8601 UTC timestamp used in pending capture frontmatter.

    Args:
        str_timestamp: Timestamp string such as `2026-04-08T21:00:00Z`.

    Returns:
        datetime | None: UTC datetime when parsing succeeds, or None when the
            timestamp is missing or malformed.
    """
    if not str_timestamp.strip():
        return None
    try:
        dt_timestamp: datetime = datetime.fromisoformat(
            str_timestamp.replace("Z", "+00:00")
        )
    except ValueError:
        return None
    dt_utc_timestamp: datetime = dt_timestamp.astimezone(UTC)
    return dt_utc_timestamp


def _related_adrs(dict_metadata: dict[str, object]) -> list[str]:
    """Extract related ADR identifiers from one parsed pending-capture metadata map.

    Args:
        dict_metadata: Frontmatter metadata parsed from a pending capture.

    Returns:
        list[str]: Sorted related ADR identifiers such as `ADR-0001`.
    """
    object_related_adrs: object = dict_metadata.get("related_adrs", [])
    if not isinstance(object_related_adrs, list):
        return []
    list_str_related_adrs: list[str] = sorted(
        {
            str(str_item).strip().upper()
            for str_item in object_related_adrs
            if str(str_item).strip()
        }
    )
    return list_str_related_adrs


def load_pending_capture_node(path_pending_shard: Path) -> dict[str, Any] | None:
    """Load one pending capture as a graph node with derived association signals.

    Args:
        path_pending_shard: Absolute path to the pending Markdown capture.

    Returns:
        dict[str, Any] | None: Node dictionary with parsed metadata plus derived
            fields such as path scopes, issue ids, and validation signals. Returns
            None when the capture cannot be parsed safely.
    """
    try:
        str_pending_text: str = path_pending_shard.read_text(encoding="utf-8")
        dict_metadata: dict[str, object]
        _body: str
        dict_metadata, _body = parse_frontmatter(str_pending_text)
    except (OSError, ValueError):
        return None

    object_files_touched: object = dict_metadata.get("files_touched", [])
    object_design_docs_touched: object = dict_metadata.get("design_docs_touched", [])
    object_verification: object = dict_metadata.get("verification", [])
    list_str_files_touched: list[str] = (
        [str(str_item) for str_item in object_files_touched]
        if isinstance(object_files_touched, list)
        else []
    )
    list_str_design_docs_touched: list[str] = (
        [str(str_item) for str_item in object_design_docs_touched]
        if isinstance(object_design_docs_touched, list)
        else []
    )
    list_str_verification: list[str] = (
        [str(str_item) for str_item in object_verification]
        if isinstance(object_verification, list)
        else []
    )
    list_str_issue_source_values: list[str] = [
        str(dict_metadata.get("branch", "")),
        str(dict_metadata.get("diff_summary", "")),
        *list_str_files_touched,
        *list_str_design_docs_touched,
        *list_str_verification,
    ]
    list_str_path_scope_keys: list[str] = _path_scope_keys(list_str_files_touched)
    list_str_issue_ids: list[str] = _issue_ids_for_values(list_str_issue_source_values)
    list_str_validation_signals: list[str] = _validation_signals(list_str_files_touched)
    dt_timestamp: datetime | None = _parse_timestamp(
        str(dict_metadata.get("timestamp", ""))
    )
    dict_node: dict[str, Any] = {
        "path": str(path_pending_shard),
        "timestamp": str(dict_metadata.get("timestamp", "")),
        "timestamp_epoch": (
            dt_timestamp.timestamp() if dt_timestamp is not None else 0.0
        ),
        "branch": str(dict_metadata.get("branch", "")),
        "thread_id": str(dict_metadata.get("thread_id", "")),
        "turn_id": str(dict_metadata.get("turn_id", "")),
        "workstream_id": str(dict_metadata.get("workstream_id", "")),
        "workstream_scope": str(dict_metadata.get("workstream_scope", "")),
        "files_touched": list_str_files_touched,
        "design_docs_touched": list_str_design_docs_touched,
        "verification": list_str_verification,
        "related_adrs": _related_adrs(dict_metadata),
        "diff_summary": str(dict_metadata.get("diff_summary", "")),
        "path_scope_keys": list_str_path_scope_keys,
        "issue_ids": list_str_issue_ids,
        "validation_signals": list_str_validation_signals,
        "primary_subsystem_hints": list_str_path_scope_keys[:5],
    }
    return dict_node


def _shared_sorted_strings(
    sequence_left: Sequence[str], sequence_right: Sequence[str]
) -> list[str]:
    """Return sorted shared strings from two input sequences.

    Args:
        sequence_left: First ordered string sequence.
        sequence_right: Second ordered string sequence.

    Returns:
        list[str]: Sorted unique shared values.
    """
    list_str_shared_values: list[str] = sorted(
        set(sequence_left).intersection(sequence_right)
    )
    return list_str_shared_values


def _temporal_score(
    float_left_timestamp: float, float_right_timestamp: float
) -> tuple[int, str | None]:
    """Return a bounded temporal-proximity score for two node timestamps.

    Args:
        float_left_timestamp: Epoch timestamp for the left node, or 0.0 when
            unavailable.
        float_right_timestamp: Epoch timestamp for the right node, or 0.0 when
            unavailable.

    Returns:
        tuple[int, str | None]: Score contribution plus an optional human-readable
            reason string.
    """
    if not float_left_timestamp or not float_right_timestamp:
        return 0, None
    float_delta_seconds: float = abs(float_left_timestamp - float_right_timestamp)
    if float_delta_seconds <= 15 * 60:
        return 5, "captured within 15 minutes"
    if float_delta_seconds <= 2 * 60 * 60:
        return 2, "captured within 2 hours"
    if float_delta_seconds <= 24 * 60 * 60:
        return 1, "captured within 24 hours"
    return 0, None


def _thread_id_counts(list_dict_nodes: Sequence[dict[str, Any]]) -> Counter[str]:
    """Count how many nodes share each thread_id across the graph.

    Singleton thread_ids (count == 1) indicate ephemeral sessions like Codex
    where the runtime creates a new thread per turn.  The edge scorer uses
    this to avoid awarding thread-match points to ephemeral ids.
    """
    counter: Counter[str] = Counter()
    for dict_node in list_dict_nodes:
        str_tid: str = str(dict_node.get("thread_id", "")).strip()
        if str_tid and str(dict_node.get("workstream_scope", "")) == "thread":
            counter[str_tid] += 1
    return counter


def score_episode_edge(
    dict_left_node: dict[str, Any],
    dict_right_node: dict[str, Any],
    counter_thread_ids: Counter[str] | None = None,
) -> dict[str, Any]:
    """Score one weighted edge between two pending-capture graph nodes.

    Args:
        dict_left_node: First node dictionary returned by load_pending_capture_node().
        dict_right_node: Second node dictionary returned by load_pending_capture_node().
        counter_thread_ids: Pre-computed thread_id frequency counts across all
            graph nodes.  When provided, singleton thread_ids (count == 1) are
            treated as ephemeral and receive no thread-match score.

    Returns:
        dict[str, Any]: Edge record with `score` and `reasons` describing the
            deterministic repo-grounded signals that support the association.
    """
    int_score: int = 0
    list_str_reasons: list[str] = []

    # --- Thread match (only for persistent threads with >1 capture) ---
    str_left_thread_id: str = str(dict_left_node.get("thread_id", "")).strip()
    str_right_thread_id: str = str(dict_right_node.get("thread_id", "")).strip()
    bool_threads_match: bool = (
        bool(str_left_thread_id)
        and str_left_thread_id == str_right_thread_id
        and str(dict_left_node.get("workstream_scope", "")) == "thread"
        and str(dict_right_node.get("workstream_scope", "")) == "thread"
    )
    if bool_threads_match:
        int_thread_count: int = (
            counter_thread_ids.get(str_left_thread_id, 0)
            if counter_thread_ids is not None
            else 2  # legacy callers without counts get full score
        )
        if int_thread_count > 1:
            int_score += 100
            list_str_reasons.append("same persistent thread_id")
        else:
            list_str_reasons.append("same thread_id (singleton, ephemeral — no score)")

    # --- Branch match (primary clustering signal for ephemeral-thread runtimes) ---
    str_left_branch: str = str(dict_left_node.get("branch", "")).strip()
    str_right_branch: str = str(dict_right_node.get("branch", "")).strip()
    if str_left_branch and str_left_branch == str_right_branch:
        int_score += 10
        list_str_reasons.append(f"same branch: {str_left_branch}")

    list_str_shared_issue_ids: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("issue_ids", [])),
        list(dict_right_node.get("issue_ids", [])),
    )
    if list_str_shared_issue_ids:
        int_score += 4
        list_str_issue_ids_excerpt: str = ", ".join(list_str_shared_issue_ids[:3])
        list_str_reasons.append(f"shared issue IDs: {list_str_issue_ids_excerpt}")

    list_str_shared_files: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("files_touched", [])),
        list(dict_right_node.get("files_touched", [])),
    )
    if list_str_shared_files:
        int_score += min(6, len(list_str_shared_files) * 3)
        list_str_shared_file_excerpt: str = ", ".join(list_str_shared_files[:3])
        list_str_reasons.append(f"shared files: {list_str_shared_file_excerpt}")

    list_str_shared_scope_keys: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("path_scope_keys", [])),
        list(dict_right_node.get("path_scope_keys", [])),
    )
    if list_str_shared_scope_keys:
        int_score += min(4, len(list_str_shared_scope_keys) * 2)
        str_scope_key_excerpt: str = ", ".join(list_str_shared_scope_keys[:3])
        list_str_reasons.append(f"shared subsystem paths: {str_scope_key_excerpt}")

    list_str_shared_design_docs: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("design_docs_touched", [])),
        list(dict_right_node.get("design_docs_touched", [])),
    )
    if list_str_shared_design_docs:
        int_score += 4
        str_design_doc_excerpt: str = ", ".join(list_str_shared_design_docs[:3])
        list_str_reasons.append(f"shared design docs: {str_design_doc_excerpt}")

    list_str_shared_adrs: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("related_adrs", [])),
        list(dict_right_node.get("related_adrs", [])),
    )
    if list_str_shared_adrs:
        int_score += 4
        str_adr_excerpt: str = ", ".join(list_str_shared_adrs[:3])
        list_str_reasons.append(f"shared ADR refs: {str_adr_excerpt}")

    list_str_shared_validation_signals: list[str] = _shared_sorted_strings(
        list(dict_left_node.get("validation_signals", [])),
        list(dict_right_node.get("validation_signals", [])),
    )
    if list_str_shared_validation_signals:
        int_score += 3
        str_validation_excerpt: str = ", ".join(list_str_shared_validation_signals[:3])
        list_str_reasons.append(
            f"shared tests/validators/hooks: {str_validation_excerpt}"
        )

    int_temporal_score: int
    str_temporal_reason: str | None
    int_temporal_score, str_temporal_reason = _temporal_score(
        float(dict_left_node.get("timestamp_epoch", 0.0)),
        float(dict_right_node.get("timestamp_epoch", 0.0)),
    )
    int_score += int_temporal_score
    if str_temporal_reason is not None:
        list_str_reasons.append(str_temporal_reason)

    dict_edge_record: dict[str, Any] = {
        "source_path": str(dict_left_node.get("path", "")),
        "target_path": str(dict_right_node.get("path", "")),
        "score": int_score,
        "reasons": list_str_reasons,
    }
    return dict_edge_record


def _cluster_nodes(
    list_dict_nodes: Sequence[dict[str, Any]],
    dict_edge_records: dict[tuple[str, str], dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Return primary episode clusters as connected components above the threshold.

    Args:
        list_dict_nodes: Ordered node dictionaries used to build the graph.
        dict_edge_records: Pairwise edge records keyed by sorted node-path tuples.

    Returns:
        list[list[dict[str, Any]]]: Deterministically ordered connected
            components using the primary edge threshold.
    """
    dict_node_by_path: dict[str, dict[str, Any]] = {
        str(dict_node["path"]): dict_node for dict_node in list_dict_nodes
    }
    dict_adjacency: dict[str, set[str]] = {
        str(dict_node["path"]): set() for dict_node in list_dict_nodes
    }
    tuple_pair_key: tuple[str, str]
    dict_edge_record: dict[str, Any]
    for tuple_pair_key, dict_edge_record in dict_edge_records.items():
        if int(dict_edge_record.get("score", 0)) < _PRIMARY_EDGE_THRESHOLD:
            continue
        str_left_path: str
        str_right_path: str
        str_left_path, str_right_path = tuple_pair_key
        dict_adjacency[str_left_path].add(str_right_path)
        dict_adjacency[str_right_path].add(str_left_path)

    set_str_visited_paths: set[str] = set()
    list_list_dict_clusters: list[list[dict[str, Any]]] = []
    list_str_all_paths: list[str] = sorted(dict_adjacency.keys())
    str_start_path: str
    for str_start_path in list_str_all_paths:
        if str_start_path in set_str_visited_paths:
            continue
        list_str_stack: list[str] = [str_start_path]
        list_dict_cluster_nodes: list[dict[str, Any]] = []
        while list_str_stack:
            str_current_path: str = list_str_stack.pop()
            if str_current_path in set_str_visited_paths:
                continue
            set_str_visited_paths.add(str_current_path)
            list_dict_cluster_nodes.append(dict_node_by_path[str_current_path])
            list_str_neighbour_paths: list[str] = sorted(
                dict_adjacency[str_current_path]
            )
            str_neighbour_path: str
            for str_neighbour_path in reversed(list_str_neighbour_paths):
                if str_neighbour_path not in set_str_visited_paths:
                    list_str_stack.append(str_neighbour_path)
        list_dict_cluster_nodes.sort(
            key=lambda dict_node: (
                str(dict_node.get("timestamp", "")),
                str(dict_node.get("path", "")),
            )
        )
        list_list_dict_clusters.append(list_dict_cluster_nodes)

    list_list_dict_clusters.sort(
        key=lambda list_dict_cluster: (
            str(list_dict_cluster[0].get("timestamp", "")),
            str(list_dict_cluster[0].get("path", "")),
        )
    )
    return list_list_dict_clusters


def _episode_scope(list_dict_cluster_nodes: Sequence[dict[str, Any]]) -> str:
    """Return the dominant episode scope for one cluster.

    Args:
        list_dict_cluster_nodes: Cluster member nodes in deterministic order.

    Returns:
        str: `thread` when the cluster shares one explicit thread id, `branch`
            when members share one branch without a unifying thread id, or
            `mixed` when the cluster spans multiple branches or incompatible ids.
    """
    set_str_thread_ids: set[str] = _thread_scoped_ids(list_dict_cluster_nodes)
    if len(set_str_thread_ids) == 1:
        return "thread"
    set_str_branches: set[str] = {
        str(dict_node.get("branch", "")).strip()
        for dict_node in list_dict_cluster_nodes
        if str(dict_node.get("branch", "")).strip()
    }
    if len(set_str_branches) <= 1:
        return "branch"
    return "mixed"


def _thread_scoped_ids(list_dict_cluster_nodes: Sequence[dict[str, Any]]) -> set[str]:
    """Return explicit thread ids from nodes whose scope is truly thread-level.

    Args:
        list_dict_cluster_nodes: Cluster member nodes in deterministic order.

    Returns:
        set[str]: Unique non-empty thread identifiers from members whose
            `workstream_scope` is `thread`.
    """
    set_str_thread_ids: set[str] = {
        str(dict_node.get("thread_id", "")).strip()
        for dict_node in list_dict_cluster_nodes
        if str(dict_node.get("thread_id", "")).strip()
        and str(dict_node.get("workstream_scope", "")).strip() == "thread"
    }
    return set_str_thread_ids


def _episode_id(list_dict_cluster_nodes: Sequence[dict[str, Any]]) -> str:
    """Derive a deterministic episode identifier for one cluster.

    Args:
        list_dict_cluster_nodes: Cluster member nodes in deterministic order.

    Returns:
        str: Stable episode identifier derived from explicit thread id when
            available, otherwise from issue ids or the earliest capture anchor.
    """
    str_scope: str = _episode_scope(list_dict_cluster_nodes)
    if str_scope == "thread":
        set_str_thread_ids: set[str] = _thread_scoped_ids(list_dict_cluster_nodes)
        str_thread_id: str = sorted(set_str_thread_ids)[0]
        return f"episode-thread-{str_thread_id}"

    set_str_issue_ids: set[str] = set()
    dict_node: dict[str, Any]
    for dict_node in list_dict_cluster_nodes:
        set_str_issue_ids.update(
            str(str_item).strip() for str_item in dict_node.get("issue_ids", [])
        )
    dict_anchor_node: dict[str, Any] = list_dict_cluster_nodes[0]
    str_anchor_id_source: str = str(dict_anchor_node.get("turn_id", "")).strip()
    if not str_anchor_id_source:
        str_anchor_id_source = Path(str(dict_anchor_node.get("path", ""))).stem
    str_anchor_slug: str = slugify(str_anchor_id_source)
    if set_str_issue_ids:
        str_issue_slug: str = slugify(sorted(set_str_issue_ids)[0])
        return f"episode-{str_issue_slug}-{str_anchor_slug}"

    str_branch_source: str = (
        str(dict_anchor_node.get("branch", "")).strip() or "unknown"
    )
    str_branch_slug: str = slugify(str_branch_source)
    return f"episode-{str_branch_slug}-{str_anchor_slug}"


def _cluster_subsystem_hints(
    list_dict_cluster_nodes: Sequence[dict[str, Any]],
) -> list[str]:
    """Return the most common subsystem hints across one cluster.

    Args:
        list_dict_cluster_nodes: Cluster member nodes in deterministic order.

    Returns:
        list[str]: Up to five common subsystem hints derived from path-scope keys.
    """
    counter_hints: Counter[str] = Counter()
    dict_node: dict[str, Any]
    for dict_node in list_dict_cluster_nodes:
        counter_hints.update(
            str(str_item) for str_item in dict_node.get("path_scope_keys", [])
        )
    list_str_subsystem_hints: list[str] = [
        str_hint for str_hint, _count in counter_hints.most_common(5)
    ]
    return list_str_subsystem_hints


def _secondary_candidate_episode_ids(
    list_dict_cluster_nodes: Sequence[dict[str, Any]],
    dict_cluster_by_path: dict[str, dict[str, Any]],
    dict_edge_records: dict[tuple[str, str], dict[str, Any]],
    str_current_episode_id: str,
) -> list[str]:
    """Return near-threshold alternate episode ids for one primary cluster.

    Args:
        list_dict_cluster_nodes: Primary cluster member nodes.
        dict_cluster_by_path: Mapping from node path to its owning manifest-like
            cluster metadata.
        dict_edge_records: Pairwise weighted edge records for all node pairs.
        str_current_episode_id: Episode id of the primary cluster.

    Returns:
        list[str]: Sorted alternate episode ids connected by near-threshold
            edges that did not cross the primary clustering threshold.
    """
    set_str_cluster_paths: set[str] = {
        str(dict_node.get("path", "")) for dict_node in list_dict_cluster_nodes
    }
    set_str_secondary_episode_ids: set[str] = set()
    tuple_pair_key: tuple[str, str]
    dict_edge_record: dict[str, Any]
    for tuple_pair_key, dict_edge_record in dict_edge_records.items():
        int_score: int = int(dict_edge_record.get("score", 0))
        if (
            int_score < _SECONDARY_EDGE_THRESHOLD
            or int_score >= _PRIMARY_EDGE_THRESHOLD
        ):
            continue
        str_left_path: str
        str_right_path: str
        str_left_path, str_right_path = tuple_pair_key
        bool_left_in_cluster: bool = str_left_path in set_str_cluster_paths
        bool_right_in_cluster: bool = str_right_path in set_str_cluster_paths
        if bool_left_in_cluster == bool_right_in_cluster:
            continue
        str_external_path: str = (
            str_right_path if bool_left_in_cluster else str_left_path
        )
        dict_external_cluster: dict[str, Any] | None = dict_cluster_by_path.get(
            str_external_path
        )
        if dict_external_cluster is None:
            continue
        str_external_episode_id: str = str(dict_external_cluster.get("episode_id", ""))
        if (
            not str_external_episode_id
            or str_external_episode_id == str_current_episode_id
        ):
            continue
        set_str_secondary_episode_ids.add(str_external_episode_id)
    list_str_secondary_episode_ids: list[str] = sorted(set_str_secondary_episode_ids)
    return list_str_secondary_episode_ids


def _manifest_edges(
    list_dict_cluster_nodes: Sequence[dict[str, Any]],
    dict_edge_records: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic edge records that connect members inside one cluster.

    Args:
        list_dict_cluster_nodes: Cluster member nodes.
        dict_edge_records: Pairwise edge records for all loaded nodes.

    Returns:
        list[dict[str, Any]]: Sorted edge records within the cluster whose score
            is at or above the secondary threshold.
    """
    set_str_cluster_paths: set[str] = {
        str(dict_node.get("path", "")) for dict_node in list_dict_cluster_nodes
    }
    list_dict_cluster_edges: list[dict[str, Any]] = []
    tuple_pair_key: tuple[str, str]
    dict_edge_record: dict[str, Any]
    for tuple_pair_key, dict_edge_record in dict_edge_records.items():
        str_left_path: str
        str_right_path: str
        str_left_path, str_right_path = tuple_pair_key
        if (
            str_left_path in set_str_cluster_paths
            and str_right_path in set_str_cluster_paths
            and int(dict_edge_record.get("score", 0)) >= _SECONDARY_EDGE_THRESHOLD
        ):
            list_dict_cluster_edges.append(dict_edge_record)
    list_dict_cluster_edges.sort(
        key=lambda dict_edge: (
            str(dict_edge.get("source_path", "")),
            str(dict_edge.get("target_path", "")),
        )
    )
    return list_dict_cluster_edges


def _cluster_manifest(
    list_dict_cluster_nodes: Sequence[dict[str, Any]],
    dict_cluster_by_path: dict[str, dict[str, Any]],
    dict_edge_records: dict[tuple[str, str], dict[str, Any]],
    *,
    str_current_pending_path: str,
) -> dict[str, Any]:
    """Build one local episode-cluster manifest from clustered node metadata.

    Args:
        list_dict_cluster_nodes: Cluster member nodes in deterministic order.
        dict_cluster_by_path: Existing path-to-cluster map used to resolve
            secondary candidate associations.
        dict_edge_records: Pairwise edge records for all loaded nodes.
        str_current_pending_path: Absolute path to the latest pending capture.

    Returns:
        dict[str, Any]: Episode manifest ready to write to local state.
    """
    str_episode_id: str = _episode_id(list_dict_cluster_nodes)
    str_episode_scope: str = _episode_scope(list_dict_cluster_nodes)
    list_str_branches: list[str] = sorted(
        {
            str(dict_node.get("branch", "")).strip()
            for dict_node in list_dict_cluster_nodes
            if str(dict_node.get("branch", "")).strip()
        }
    )
    list_str_member_paths: list[str] = [
        str(dict_node.get("path", "")) for dict_node in list_dict_cluster_nodes
    ]
    list_dict_cluster_edges: list[dict[str, Any]] = _manifest_edges(
        list_dict_cluster_nodes, dict_edge_records
    )
    dict_latest_node: dict[str, Any] = max(
        list_dict_cluster_nodes,
        key=lambda dict_node: (
            float(dict_node.get("timestamp_epoch", 0.0)),
            str(dict_node.get("path", "")),
        ),
    )
    list_str_secondary_episode_ids: list[str] = _secondary_candidate_episode_ids(
        list_dict_cluster_nodes,
        dict_cluster_by_path,
        dict_edge_records,
        str_episode_id,
    )
    str_status: str = "ambiguous" if list_str_secondary_episode_ids else "active"
    dict_manifest: dict[str, Any] = {
        "episode_id": str_episode_id,
        "episode_scope": str_episode_scope,
        "status": str_status,
        "branches": list_str_branches,
        "member_count": len(list_dict_cluster_nodes),
        "member_pending_shard_paths": list_str_member_paths,
        "member_nodes": list(list_dict_cluster_nodes),
        "cluster_edges": list_dict_cluster_edges,
        "primary_subsystem_hints": _cluster_subsystem_hints(list_dict_cluster_nodes),
        "secondary_candidate_episode_ids": list_str_secondary_episode_ids,
        "latest_pending_shard_path": str(dict_latest_node.get("path", "")),
        "current_pending_shard_path": (
            str_current_pending_path
            if str_current_pending_path in list_str_member_paths
            else ""
        ),
    }
    return dict_manifest


def rebuild_episode_graph(
    repo_root: Path,
    path_current_pending_shard: Path,
    *,
    limit: int = _MAX_GRAPH_PENDING_CAPTURES,
) -> dict[str, Any]:
    """Rebuild local episode manifests and return the active cluster for one capture.

    Args:
        repo_root: Absolute path to the repository root.
        path_current_pending_shard: Absolute path to the latest pending capture
            that triggered graph rebuild.
        limit: Maximum number of pending captures to consider.

    Returns:
        dict[str, Any]: Active episode-cluster manifest for the current pending
            capture, including `manifest_path` for the written local state file.

    Raises:
        ValueError: Raised when the current pending capture cannot be parsed into
            graph-node metadata.
    """
    list_path_pending_shards: list[Path] = _pending_capture_paths(
        repo_root, limit=limit
    )
    list_dict_nodes: list[dict[str, Any]] = []
    path_pending_shard: Path
    for path_pending_shard in list_path_pending_shards:
        dict_node: dict[str, Any] | None = load_pending_capture_node(path_pending_shard)
        if dict_node is None:
            continue
        list_dict_nodes.append(dict_node)

    list_dict_nodes.sort(
        key=lambda dict_node: (
            str(dict_node.get("timestamp", "")),
            str(dict_node.get("path", "")),
        )
    )
    str_current_pending_path: str = str(path_current_pending_shard)
    if str_current_pending_path not in {
        str(dict_node.get("path", "")) for dict_node in list_dict_nodes
    }:
        raise ValueError(
            f"current pending capture is missing from episode graph rebuild: {path_current_pending_shard}"
        )

    counter_thread_ids: Counter[str] = _thread_id_counts(list_dict_nodes)
    dict_edge_records: dict[tuple[str, str], dict[str, Any]] = {}
    int_left_idx: int
    for int_left_idx in range(len(list_dict_nodes)):
        int_right_idx: int
        for int_right_idx in range(int_left_idx + 1, len(list_dict_nodes)):
            dict_left_node: dict[str, Any] = list_dict_nodes[int_left_idx]
            dict_right_node: dict[str, Any] = list_dict_nodes[int_right_idx]
            tuple_pair_key: tuple[str, str] = tuple(
                sorted(
                    (
                        str(dict_left_node.get("path", "")),
                        str(dict_right_node.get("path", "")),
                    )
                )
            )
            dict_edge_records[tuple_pair_key] = score_episode_edge(
                dict_left_node, dict_right_node, counter_thread_ids
            )

    list_list_dict_clusters: list[list[dict[str, Any]]] = _cluster_nodes(
        list_dict_nodes, dict_edge_records
    )
    list_dict_manifests: list[dict[str, Any]] = []
    dict_cluster_by_path: dict[str, dict[str, Any]] = {}

    list_dict_cluster_nodes: list[dict[str, Any]]
    for list_dict_cluster_nodes in list_list_dict_clusters:
        dict_placeholder_manifest: dict[str, Any] = {
            "episode_id": _episode_id(list_dict_cluster_nodes)
        }
        dict_node: dict[str, Any]
        for dict_node in list_dict_cluster_nodes:
            dict_cluster_by_path[str(dict_node.get("path", ""))] = (
                dict_placeholder_manifest
            )

    for list_dict_cluster_nodes in list_list_dict_clusters:
        dict_manifest: dict[str, Any] = _cluster_manifest(
            list_dict_cluster_nodes,
            dict_cluster_by_path,
            dict_edge_records,
            str_current_pending_path=str_current_pending_path,
        )
        list_dict_manifests.append(dict_manifest)
        dict_node = {}
        for dict_node in list_dict_cluster_nodes:
            dict_cluster_by_path[str(dict_node.get("path", ""))] = dict_manifest

    path_manifest_dir: Path = episode_manifest_dir(repo_root)
    set_str_expected_manifest_names: set[str] = set()
    dict_manifest: dict[str, Any]
    for dict_manifest in list_dict_manifests:
        str_episode_id: str = str(dict_manifest.get("episode_id", "")).strip()
        path_manifest: Path = path_manifest_dir / f"{str_episode_id}.json"
        dict_manifest_with_path: dict[str, Any] = dict(dict_manifest)
        dict_manifest_with_path["manifest_path"] = str(path_manifest)
        write_text(
            path_manifest,
            json.dumps(dict_manifest_with_path, indent=2, sort_keys=True) + "\n",
        )
        dict_manifest.update({"manifest_path": str(path_manifest)})
        set_str_expected_manifest_names.add(path_manifest.name)

    path_existing_manifest: Path
    for path_existing_manifest in path_manifest_dir.glob("*.json"):
        if path_existing_manifest.name not in set_str_expected_manifest_names:
            path_existing_manifest.unlink(missing_ok=True)

    dict_active_manifest: dict[str, Any] | None = dict_cluster_by_path.get(
        str_current_pending_path
    )
    if dict_active_manifest is None:
        raise ValueError(
            f"current pending capture did not resolve to an episode cluster: {path_current_pending_shard}"
        )
    return dict_active_manifest
