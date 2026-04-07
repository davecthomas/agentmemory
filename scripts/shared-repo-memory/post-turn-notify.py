#!/usr/bin/env python3
"""post-turn-notify.py -- Post-turn hook for the shared repo-memory system.

This script fires after every agent turn.  Its job is to decide whether the
turn was meaningful and, if so, write a permanent event shard capturing what
changed, why, and what comes next.

The "meaningful turn" gate
--------------------------
A shard is written only when tracked files changed in the working tree
(files_touched is non-empty).  Conversational turns with no repo changes --
even long discussions that mention ADRs or decisions -- produce no shard.
This prevents the memory from filling up with noise and false-positive
decision candidates.

Triggered by:
  - Claude Code:  Stop hook (CLAUDECODE=1 env var, hookEventName == "Stop")
  - Gemini CLI:   AfterAgent hook (hookEventName == "AfterAgent")
  - Codex CLI:    Invoked directly via scripts/shared-repo-memory/notify-wrapper.sh

After writing the shard, this script:
  1. Calls rebuild-summary.py to regenerate today's summary.md from all shards.
  2. Stages the shard and rebuilt summary via git add (never commits).

Install location after `./install.sh`:
  ~/.agent/shared-repo-memory/post-turn-notify.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

from adapters import ClaudeAdapter, detect_adapter, detect_adapter_from_hook_event
from common import (
    append_hook_trace,
    author_slug,
    collect_matches,
    current_branch,
    ensure_dir,
    find_first,
    flatten_strings,
    info,
    render_frontmatter,
    run,
    safe_main,
    stage_paths,
    tracked_changed_files,
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


def _diff_hash(repo_root: Path, files: list[str]) -> str:
    """Return an MD5 of 'git diff HEAD -- <files>' for the given file list.

    An empty diff (all changes already staged/committed) produces a hash of
    the empty string, which is still a valid stable value to compare against.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--"] + files,
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        return hashlib.md5(result.stdout).hexdigest()
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


# ---------------------------------------------------------------------------
# Design doc detection patterns
# ---------------------------------------------------------------------------

_DESIGN_DOC_PATTERNS: list[str] = [
    "docs/",
    "design",
    "spec",
    "arch",
    "adr",
]


def _is_design_doc(file_path: str) -> bool:
    """Return True if a file path looks like a design document.

    Args:
        file_path: Repo-relative file path.

    Returns:
        bool: True when the path matches any design doc pattern.
    """
    str_lower: str = file_path.lower()
    return any(pattern in str_lower for pattern in _DESIGN_DOC_PATTERNS)


# ---------------------------------------------------------------------------
# Async subagent spawning: shard enrichment and ADR inspection
# ---------------------------------------------------------------------------

def _open_enrichment_log(repo_root: Path) -> object:
    """Open (or create) the enrichment log file for subprocess output.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        File handle for the enrichment log.
    """
    log_dir: Path = repo_root / ".agents" / "memory" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return open(log_dir / "enrichment.log", "a")  # noqa: SIM115


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
    cmd: list[str] | None = adapter.build_bootstrap_command(
        skill_content, task, repo_root
    )
    if cmd is None:
        cmd = ClaudeAdapter.build_bootstrap_command(
            skill_content, task, repo_root
        )
    if cmd is None:
        return False

    log_file: object = _open_enrichment_log(repo_root)
    try:
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        return True
    except OSError:
        warn(f"enrichment subagent launch failed for {adapter.agent_id()}")
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

    cmd: list[str] | None = adapter.build_bootstrap_command(
        skill_content, task, repo_root
    )
    if cmd is None:
        cmd = ClaudeAdapter.build_bootstrap_command(skill_content, task, repo_root)
    if cmd is None:
        return False

    log_file: object = _open_enrichment_log(repo_root)
    try:
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        return True
    except OSError:
        warn(f"ADR inspection subagent launch failed for {adapter.agent_id()}")
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
    print(adapter.render_hook_response(HookResponse(status=status, message=message, extra=filtered)))


def main() -> int:
    """Post-turn hook entry point.

    Reads the hook payload from stdin, evaluates whether the turn was meaningful,
    writes a shard if so, and rebuilds the daily summary.

    Returns:
        int: 0 on success or graceful noop; 1 on hard error.
    """
    args = parse_args()
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

    # Normalize the payload into a canonical request.
    req = adapter.normalize_hook_request(payload)

    # Claude Code injects the working directory into the payload as "cwd".
    # Prefer that over os.getcwd() so the hook operates on the correct repo when
    # Claude Code changes directory during a session.
    cwd_override = req.cwd or args.repo_root
    repo_root = try_repo_root(cwd_override)
    if repo_root is None:
        _emit(adapter, "noop", message="current working directory is not inside a Git repository")
        return 0

    append_hook_trace("Notify", "started", repo_root=repo_root)

    # Save the raw payload for debugging; stored in .codex/local/ which is never committed.
    local_root = ensure_dir(repo_root / ".codex" / "local")
    write_text(
        local_root / "last-notify-payload.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )

    # Canonical memory directory must exist; it is created by bootstrap-repo.sh
    # which SessionStart calls on every session open.
    if not (repo_root / ".agents" / "memory").is_dir():
        append_hook_trace(
            "Notify",
            "error",
            repo_root=repo_root,
            details={"reason": "missing_agents_memory_dir"},
        )
        warn(
            "missing .agents/memory/; run bootstrap-repo.sh or re-open Claude to trigger SessionStart"
        )
        _emit(adapter, "error", message="missing .agents/memory/ directory; repo not bootstrapped")
        return 1

    # Collect evidence and metadata from the payload.
    strings = flatten_strings(payload)
    files_touched = tracked_changed_files(repo_root)
    verification = collect_matches(
        strings,
        r"\b(pass(ed)?|fail(ed|ure)?|error|warning|test|lint|build|verified?)\b",
    )
    blockers = collect_matches(
        strings, r"\b(blocked|blocker|waiting on|cannot|can't|stuck)\b"
    )
    # Meaningful turn gate: a shard is ONLY written when tracked files changed.
    # Decision keyword matches alone are insufficient -- every discussion of this
    # system's own design would match, producing shards with no real content.
    if not files_touched:
        append_hook_trace(
            "Notify", "noop", repo_root=repo_root, details={"reason": "not_meaningful"}
        )
        _emit(adapter, "noop", message="notify payload was not meaningful; no shard written")
        return 0

    # Build shard identity fields from the normalised request.
    # Fall back to stable hash-based identifiers when the payload lacks explicit IDs.
    thread_id = (req.thread_id or stable_identifier("thread", payload)).replace(" ", "_")
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
        _emit(adapter, "noop", message="diff unchanged since last shard for this thread; skipping duplicate")
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
    turn_id = (
        req.turn_id or stable_identifier("turn", payload_for_turn_hash)
    ).replace(" ", "_")

    # Extract "why" text: prefer the user's prompt, fall back to the assistant response.
    prompt = req.prompt
    if not prompt and req.transcript_path:
        prompt = extract_user_prompt_from_transcript(req.transcript_path)

    # Why: prefer the user prompt that drove the change. When prompt text is
    # unavailable or too weak, fall back to a diff summary rather than assistant
    # chatter so durable memory stays high-signal.
    diff_summary = _diff_summary(repo_root, files_touched)
    why_lines = build_why_lines(prompt, diff_summary)

    what_lines = [f"- Updated {path}" for path in files_touched] or [
        "- No tracked files were detected."
    ]
    # Evidence: include the git diff summary as a concrete signal when available.
    evidence_lines = verification[:]
    if diff_summary:
        evidence_lines.insert(0, f"- git diff: {diff_summary}")
    if not evidence_lines:
        evidence_lines = ["- Tracked repo changes were detected in the working tree."]
    next_lines = blockers or [
        "- Review the generated shard and summary, then explicitly commit and push them with the related code changes if ready."
    ]

    # Scan the payload for any ADR cross-references so we can link them in the shard.
    related_adrs = sorted(
        set(re.findall(r"\bADR-\d{4}\b", "\n".join(strings), re.IGNORECASE))
    )

    # Determine the shard output path.
    day_dir = ensure_dir(repo_root / ".agents/memory" / "daily" / timestamp[:10])
    events_dir = ensure_dir(day_dir / "events")

    # Idempotency: if a shard for this thread+turn already exists, keep it.
    existing_shards: list[Path] = list(
        events_dir.glob(f"*--thread_{thread_id}--turn_{turn_id}.md")
    )
    if existing_shards:
        shard_path = existing_shards[0]
        # Preserve the original timestamp from the filename so re-runs don't drift.
        # Shard filenames use dashes instead of colons in the time portion
        # (e.g. "2026-04-02T23-27-09Z") for filesystem safety; reconstruct the
        # canonical ISO-8601 form by restoring colons in the time part only.
        raw_ts: str = shard_path.name.split("--")[0]
        date_str: str
        time_str: str
        date_str, time_str = raw_ts.split("T", 1)
        timestamp = f"{date_str}T{time_str.replace('-', ':')}"
    else:
        basename = f"{timestamp.replace(':', '-')}--{author}--thread_{thread_id}--turn_{turn_id}"
        shard_path = events_dir / f"{basename}.md"

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
    write_text(shard_path, "\n".join(body_lines))

    # Rebuild today's summary from the full shard set (including the new shard).
    try:
        run(
            [
                sys.executable,
                str(Path(__file__).with_name("rebuild-summary.py")),
                "--repo-root",
                str(repo_root),
                "--date",
                timestamp[:10],
            ],
            cwd=repo_root,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # Log the actual error so it's diagnosable -- previously swallowed.
        warn(f"rebuild-summary.py failed (exit {exc.returncode})")
        if exc.stdout:
            warn(f"  stdout: {exc.stdout.strip()}")
        if exc.stderr:
            warn(f"  stderr: {exc.stderr.strip()}")
        append_hook_trace(
            "Notify",
            "error",
            repo_root=repo_root,
            details={
                "reason": "rebuild_summary_failed",
                "exit_code": exc.returncode,
                "stderr": (exc.stderr or "")[:1000],
            },
        )
        # Shard was already written; degrade gracefully rather than aborting.
        _emit(adapter, "error", message=f"shard written but summary rebuild failed: {(exc.stderr or '').strip()[:200]}")
        return 1

    summary_path = day_dir / "summary.md"
    if not summary_path.exists():
        warn("summary rebuild did not produce summary.md")
        _emit(adapter, "error", message="summary rebuild did not produce summary.md")
        return 1

    # Persist the diff hash so subsequent turns can detect unchanged diffs and
    # skip writing duplicate shards for the same working-tree state.
    _save_diff_state(repo_root, thread_id, current_diff_hash)

    # Stage the shard and rebuilt summary so they are ready to commit alongside
    # the code changes.  The developer must commit explicitly -- this system
    # never auto-commits.
    stage_paths(
        repo_root,
        [shard_path.relative_to(repo_root), summary_path.relative_to(repo_root)],
    )

    # --- Async Phase 2: shard enrichment via subagent ---
    # Save enrichment context for the subagent to read, then fire-and-forget.
    # The raw shard is already written and staged; enrichment improves it
    # asynchronously without blocking the hook.
    bool_enrichment_spawned: bool = False
    assistant_text: str = req.assistant_text or ""
    if assistant_text or prompt:
        context_data: dict[str, object] = {
            "shard_path": str(shard_path),
            "repo_root": str(repo_root),
            "assistant_text": assistant_text[:8000],
            "prompt": prompt or "",
            "files_touched": files_touched,
            "diff_summary": diff_summary,
        }
        context_filename: str = f".enrich-{turn_id}.json"
        context_path: Path = events_dir / context_filename
        try:
            write_text(context_path, json.dumps(context_data, indent=2, sort_keys=True) + "\n")
            bool_enrichment_spawned = _spawn_enrichment(adapter, context_path, repo_root)
            if bool_enrichment_spawned:
                info(f"spawned enrichment subagent for {shard_path.name}")
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
            info(f"spawned ADR inspection subagent for {len(design_docs)} design doc(s)")

    append_hook_trace(
        "Notify",
        "success",
        repo_root=repo_root,
        details={
            "files_touched": files_touched,
            "shard_path": str(shard_path.relative_to(repo_root)),
            "summary_path": str(summary_path.relative_to(repo_root)),
            "thread_id": thread_id,
            "turn_id": turn_id,
            "enrichment_spawned": bool_enrichment_spawned,
            "adr_inspection_spawned": bool_inspection_spawned,
            "design_docs_touched": design_docs,
        },
    )
    info(f"wrote {shard_path.relative_to(repo_root)}")
    _emit(
        adapter,
        "ok",
        shard_path=str(shard_path.relative_to(repo_root)),
        summary_path=str(summary_path.relative_to(repo_root)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "Notify"))
