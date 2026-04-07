#!/usr/bin/env python3
"""post-turn-notify.py -- Post-turn hook for the shared repo-memory system.

This script fires after every agent turn. Its job is to decide whether the turn
was meaningful and, if so, write a local pending shard capturing the mechanical
facts needed for semantic publication later.

The "meaningful turn" gate
--------------------------
A pending raw shard is written only when repo files changed in the working tree
(files_touched is non-empty).  Conversational turns with no repo changes --
even long discussions that mention ADRs or decisions -- produce no shard.
This prevents the memory from filling up with noise and false-positive
decision candidates.

Triggered by:
  - Claude Code:  Stop hook (CLAUDECODE=1 env var, hookEventName == "Stop")
  - Gemini CLI:   AfterAgent hook (hookEventName == "AfterAgent")
  - Codex CLI:    Invoked directly via scripts/shared-repo-memory/notify-wrapper.sh

After writing the pending shard, this script may:
  1. Save enrichment context and spawn an async subagent to publish an enriched
     shard into `.agents/memory/daily/<date>/events/`.
  2. Spawn an ADR inspection subagent when changed design docs were touched.

The raw pending shard is local-only and must never be committed. Publication,
summary rebuild, and staging happen only inside enrich-shard.py after semantic
content is available.

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
    PENDING_SHARDS_RELATIVE_DIR,
    append_hook_trace,
    author_slug,
    changed_repo_files,
    collect_matches,
    current_branch,
    ensure_dir,
    find_first,
    flatten_strings,
    format_log_prefix,
    info,
    render_frontmatter,
    runtime_provider_version,
    safe_main,
    set_runtime_log_context,
    try_repo_root,
    utc_now,
    utc_timestamp,
    warn,
    write_text,
)
from models import HookResponse


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with optional repo_root attribute.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=False)
    return parser.parse_args()


def extract_user_prompt_from_transcript(transcript_path: str) -> str | None:
    """Read the JSONL transcript and return the last human/user turn text.

    Claude Code writes a JSONL transcript file during each session.  When the
    hook payload does not include the user prompt directly, we fall back to
    reading the last human-role entry from the transcript file referenced in
    the payload.

    Args:
        transcript_path: Absolute path to the session transcript JSONL file.

    Returns:
        str | None: Up to 500 characters of the most recent user turn text,
            or None if the transcript is absent, unreadable, or has no human turns.
    """
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            role = entry.get("role", "")
            if role not in ("human", "user"):
                continue
            content = entry.get("content", "")
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                # Content may be a list of typed blocks; extract text blocks only.
                parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = " ".join(parts).strip()
            else:
                continue
            if text:
                return text[:500]
    except OSError:
        pass
    return None


def stable_identifier(prefix: str, payload: dict[str, object]) -> str:
    """Derive a stable short identifier from a JSON payload hash.

    Used when the hook payload does not provide a thread_id or turn_id directly.
    The SHA-1 of the serialized payload provides a deterministic, collision-
    resistant identifier that is stable across retries with the same payload.

    Args:
        prefix: Short string prepended to the hash, e.g. "thread" or "turn".
        payload: JSON-serialisable dict to hash.

    Returns:
        str: Identifier of the form "<prefix>_<10-char hex>".
    """
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest[:10]}"


# ---------------------------------------------------------------------------
# Diff-hash deduplication
# ---------------------------------------------------------------------------

_DIFF_STATE_FILE = ".codex/local/last-shard-diff-state.json"


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


def _diff_hash(repo_root: Path, files: list[str]) -> str:
    """Return a stable hash of the current change content for the given files.

    The hash includes both tracked Git diff output and the raw bytes of any
    untracked files. This prevents new-file turns from collapsing to the same
    empty-diff hash and preserves deduplication behavior across tracked and
    untracked changes.
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
                digest.update(path_file.read_bytes())
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
# Git diff summary for Why content
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


def normalize_why_text(str_text: str) -> str:
    """Collapse whitespace in candidate Why text and trim the result.

    Args:
        str_text: Raw candidate Why text collected from a prompt or diff summary.

    Returns:
        str: Normalized single-line text, or an empty string when no meaningful
            content remains after normalization.
    """
    str_normalized_text: str = " ".join(str_text.split()).strip()
    return str_normalized_text  # Normal exit.


def is_useful_prompt_for_why(str_prompt: str) -> bool:
    """Return True when a user prompt is strong enough to seed shard Why content.

    Args:
        str_prompt: Candidate user prompt text after extraction from the hook
            payload or transcript.

    Returns:
        bool: True when the prompt is long enough to communicate a concrete task;
            False when it is too short or empty to serve as durable memory.
    """
    str_normalized_prompt: str = normalize_why_text(str_prompt)
    bool_is_useful: bool = len(str_normalized_prompt) >= 15
    return bool_is_useful  # Normal exit.


def build_why_lines(str_prompt: str | None, str_diff_summary: str) -> list[str]:
    """Construct the shard Why section from high-signal inputs only.

    Args:
        str_prompt: Extracted user prompt text when available.
        str_diff_summary: Compact Git diff summary describing the repo changes.

    Returns:
        list[str]: One bullet line for the shard Why section. The result prefers
            a qualifying user task, otherwise a diff summary, otherwise a neutral
            fallback describing that the repo changed during the turn.
    """
    list_str_why_lines: list[str] = []
    if str_prompt and is_useful_prompt_for_why(str_prompt):
        str_prompt_line: str = normalize_why_text(str_prompt)
        list_str_why_lines.append(f"- {str_prompt_line}")
        return list_str_why_lines  # Normal exit.
    str_diff_line: str = normalize_why_text(str_diff_summary)
    if str_diff_line:
        list_str_why_lines.append(f"- {str_diff_line}")
        return list_str_why_lines  # Normal exit.
    list_str_why_lines.append("- Repo state changed during this agent turn.")
    return list_str_why_lines  # Normal exit.


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
# Async subagent spawning: shard enrichment and ADR inspection
# ---------------------------------------------------------------------------


def _open_enrichment_log(repo_root: Path) -> TextIO:
    """Open (or create) the enrichment log file for subprocess output.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        File handle for the enrichment log.
    """
    log_dir: Path = repo_root / ".agents" / "memory" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return open(log_dir / "enrichment.log", "a")  # noqa: SIM115


def _enrichment_context_dir(repo_root: Path) -> Path:
    """Return the ignored directory used for ephemeral enrichment context files.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Path: Absolute path to the local-only enrichment context directory.
    """
    path_context_dir: Path = ensure_dir(
        repo_root / ".agents" / "memory" / "logs" / "enrichment-context"
    )
    return path_context_dir


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
            launcher agent id, and the launcher provider version. When no
            launch path exists, the command element is None and the metadata is
            set to "unknown".
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
        return None, "unknown", "unknown"

    str_launcher_provider_version: str = runtime_provider_version(str_launcher_agent_id)
    return list_str_cmd, str_launcher_agent_id, str_launcher_provider_version


def _subagent_env(
    str_launcher_agent_id: str, str_launcher_provider_version: str
) -> dict[str, str]:
    """Build environment overrides for spawned enrichment-related subprocesses.

    Args:
        str_launcher_agent_id: Runtime that is launching the subagent, such as
            "claude" or "gemini".
        str_launcher_provider_version: Resolved CLI version for the launcher.

    Returns:
        dict[str, str]: Copy of os.environ plus explicit shared-memory runtime
            metadata consumed by common.py log helpers in descendant processes.
    """
    dict_env: dict[str, str] = dict(os.environ)
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
        str_action: Short action label such as "enrichment" or "ADR inspection".
        str_launcher_agent_id: Runtime used to launch the subagent.
        str_launcher_provider_version: Resolved CLI version for that runtime.
        cmd: Full subprocess command that will be executed.

    Returns:
        None: One header line is appended and flushed to the log file.
    """
    str_command_name: str = cmd[0] if cmd else "unknown"
    str_prefix: str = format_log_prefix(
        str_launcher_agent_id, str_launcher_provider_version
    )
    log_file.write(f"{str_prefix} starting {str_action} via {str_command_name}\n")
    log_file.flush()


def _spawn_enrichment(
    adapter: type,
    context_path: Path,
    repo_root: Path,
) -> bool:
    """Fire-and-forget a subagent to enrich a raw shard with semantic content.

    Loads the shard-enricher skill and spawns the subagent via the adapter's CLI.
    Falls back to ClaudeAdapter when the adapter cannot spawn subagents.

    Args:
        adapter: The detected runtime adapter class.
        context_path: Absolute path to the enrichment context JSON file.
        repo_root: Absolute path to the repository root.

    Returns:
        bool: True if a subprocess was launched, False if skipped.
    """
    skill_path: Path = Path.home() / ".agent" / "skills" / "shard-enricher" / "SKILL.md"
    if not skill_path.exists():
        warn("shard-enricher skill not installed; skipping enrichment")
        return False

    skill_content: str = skill_path.read_text(encoding="utf-8")
    task: str = f"Enrich the shard using context at: {context_path}"
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
            str_action="enrichment",
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
        warn(f"enrichment subagent launch failed for {str_launcher_agent_id}")
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

    Reads the hook payload from stdin, evaluates whether the turn was meaningful,
    writes a pending shard if so, and optionally spawns async publication work.

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

    # Save the raw payload for debugging; stored in .codex/local/ which is never committed.
    local_root = ensure_dir(repo_root / ".codex" / "local")
    write_text(
        local_root / "last-notify-payload.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )

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

    # Collect evidence and metadata from the payload.
    strings = flatten_strings(payload)
    files_touched = changed_repo_files(repo_root)
    verification = collect_matches(
        strings,
        r"\b(pass(ed)?|fail(ed|ure)?|error|warning|test|lint|build|verified?)\b",
    )
    blockers = collect_matches(
        strings, r"\b(blocked|blocker|waiting on|cannot|can't|stuck)\b"
    )
    # Meaningful turn gate: a shard is ONLY written when repo files changed.
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
    thread_id = (req.thread_id or stable_identifier("thread", payload)).replace(
        " ", "_"
    )
    model = adapter.resolve_model(payload)

    # Diff-hash deduplication gate: git status is sticky -- once a file is
    # modified it appears in every subsequent turn until committed.  Hash the
    # actual diff content so we only write a new shard when the working-tree
    # content has genuinely changed since the last captured shard for this thread.
    current_diff_hash = _diff_hash(repo_root, files_touched)
    if _already_captured(repo_root, thread_id, current_diff_hash):
        append_hook_trace(
            "Notify",
            "noop",
            repo_root=repo_root,
            details={"reason": "diff_unchanged_since_last_shard"},
        )
        _emit(
            adapter,
            "noop",
            message="diff unchanged since last shard for this thread; skipping duplicate",
        )
        return 0

    now = utc_now()
    timestamp = utc_timestamp(now)
    author = author_slug(repo_root)
    branch = current_branch(repo_root)

    # Exclude volatile fields from the turn hash so the same logical turn
    # produces the same turn_id even if the payload timestamp changes between retries.
    volatile_keys = {
        "timestamp",
        "hook_event_name",
        "stop_hook_active",
        "hookEventName",
    }
    payload_for_turn_hash = {k: v for k, v in payload.items() if k not in volatile_keys}
    turn_id = (req.turn_id or stable_identifier("turn", payload_for_turn_hash)).replace(
        " ", "_"
    )

    # Extract "why" seed text from the user task, optionally via transcript fallback.
    prompt = req.prompt
    if not prompt and req.transcript_path:
        prompt = extract_user_prompt_from_transcript(req.transcript_path)

    # Why: prefer the user prompt that drove the change. When prompt text is
    # unavailable or too weak, fall back to a diff summary rather than assistant
    # chatter so durable memory stays high-signal.
    diff_summary = _diff_summary(repo_root, files_touched)
    why_lines = build_why_lines(prompt, diff_summary)

    what_lines = [f"- Updated {path}" for path in files_touched] or [
        "- No repo files were detected."
    ]
    # Evidence: include the git diff summary as a concrete signal when available.
    evidence_lines = verification[:]
    if diff_summary:
        evidence_lines.insert(0, f"- git diff: {diff_summary}")
    if not evidence_lines:
        evidence_lines = ["- Repo changes were detected in the working tree."]
    next_lines = blockers or [
        "- Wait for enrichment to publish a durable shard before committing shared memory artifacts."
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
            ("decision_candidate", False),
            ("enriched", False),
            ("ai_generated", True),
            ("ai_model", model),
            ("ai_tool", ai_tool),
            ("ai_surface", ai_surface),
            ("ai_executor", "local-agent"),
            ("related_adrs", related_adrs),
            ("files_touched", files_touched),
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
    write_text(path_pending_shard, "\n".join(body_lines))

    # Persist the diff hash so subsequent turns can detect unchanged diffs and
    # skip writing duplicate pending shards for the same working-tree state.
    _save_diff_state(repo_root, thread_id, current_diff_hash)

    # --- Async Phase 2: shard enrichment via subagent ---
    # Save enrichment context for the subagent to read, then fire-and-forget.
    # The pending shard is local-only. Publication into the committed daily
    # namespace happens only if enrich-shard.py runs successfully.
    bool_enrichment_spawned: bool = False
    assistant_text: str = req.assistant_text or ""
    if assistant_text or prompt:
        context_data: dict[str, object] = {
            "shard_path": str(path_pending_shard),
            "published_shard_path": str(path_published_shard),
            "repo_root": str(repo_root),
            "assistant_text": assistant_text[:8000],
            "prompt": prompt or "",
            "files_touched": files_touched,
            "diff_summary": diff_summary,
        }
        context_filename: str = f".enrich-{turn_id}.json"
        path_context_dir: Path = _enrichment_context_dir(repo_root)
        context_path: Path = path_context_dir / context_filename
        try:
            write_text(
                context_path, json.dumps(context_data, indent=2, sort_keys=True) + "\n"
            )
            bool_enrichment_spawned = _spawn_enrichment(
                adapter, context_path, repo_root
            )
            if bool_enrichment_spawned:
                info(f"spawned enrichment subagent for {path_published_shard.name}")
            elif context_path.exists():
                # No subagent CLI available; clean up context file.
                context_path.unlink(missing_ok=True)
        except OSError as error:
            warn(f"failed to write enrichment context: {error}")

    # --- Async Phase 2b: design doc ADR inspection ---
    # When the turn touched design docs, spawn a separate subagent to inspect
    # them for ADR-worthy decisions.  Independent of shard enrichment.
    design_docs: list[str] = [path for path in files_touched if _is_design_doc(path)]
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
            "enrichment_spawned": bool_enrichment_spawned,
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
