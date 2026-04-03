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
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

from common import (
    append_hook_trace,
    author_slug,
    collect_matches,
    current_branch,
    emit_hook_response,
    ensure_dir,
    find_first,
    flatten_strings,
    info,
    read_claude_model,
    read_codex_model,
    render_frontmatter,
    run,
    stage_paths,
    tracked_changed_files,
    try_repo_root,
    utc_now,
    utc_timestamp,
    warn,
    write_text,
)

# ---------------------------------------------------------------------------
# Payload key sets -- agents and platforms use different field names for the
# same logical concepts.  find_first() searches recursively through any of
# these aliases so we get the right value regardless of the calling agent.
# ---------------------------------------------------------------------------

# Keys that may carry the conversation / session / thread identifier.
THREAD_KEYS = {
    "thread_id",
    "threadId",
    "conversation_id",
    "conversationId",
    "session_id",
    "sessionId",
}

# Keys that may carry the individual turn identifier.
TURN_KEYS = {"turn_id", "turnId", "id"}

# Keys that may carry the user's prompt text.
PROMPT_KEYS = {"prompt", "user_prompt", "userPrompt", "inputText", "input_text"}

# Keys that may carry the assistant's most recent response text.
ASSISTANT_KEYS = {
    "last_assistant_message",
    "lastAssistantMessage",
    "output_text",
    "summary_text",
    "reasoning_text",
    "prompt_response",
    "text",
    "content",
}


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
    The SHA-1 of the serialised payload provides a deterministic, collision-
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


def extract_model(payload: dict[str, object]) -> str | None:
    """Attempt to resolve the AI model name from the hook payload or agent config.

    Resolution order:
      1. model / model_name / modelName keys anywhere in the payload.
      2. CLAUDE_MODEL env var via read_claude_model().
      3. model key in ~/.codex/config.toml via read_codex_model().

    Args:
        payload: The raw hook payload dict.

    Returns:
        str | None: Model identifier string, or None if all sources are absent.
    """
    model = find_first(payload, {"model", "model_name", "modelName"})
    if model:
        return model
    home = Path.home()
    return read_claude_model(home) or read_codex_model(home)


def decision_candidate(strings: list[str]) -> bool:
    """Return True if any string in the payload suggests an architectural decision was made.

    Scans for keywords associated with deliberate design choices: "decision",
    "policy", "contract", "standard", "repo rule", "adr", "must read", "governing".

    Note: This is used only to annotate the shard's decision_candidate field.
    It is NOT used as a gate for whether a shard is written -- that gate is
    files_touched.  This prevents conversational mentions of these keywords
    from generating false-positive shards with no real content.

    Args:
        strings: Pre-flattened string values from the hook payload.

    Returns:
        bool: True if any string contains a decision keyword.
    """
    pattern = re.compile(
        r"\b(decision|policy|contract|standard|repo rule|adr|must read|governing)\b",
        re.IGNORECASE,
    )
    return any(pattern.search(value) for value in strings)


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
        emit_hook_response("error", message="invalid JSON payload")
        return 1

    # Claude Code injects the working directory into the payload as "cwd".
    # Prefer that over os.getcwd() so the hook operates on the correct repo when
    # Claude Code changes directory during a session.
    cwd_override = payload.get("cwd") or args.repo_root
    repo_root = try_repo_root(cwd_override)
    if repo_root is None:
        emit_hook_response(
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
        emit_hook_response(
            "error", message="missing .agents/memory/ directory; repo not bootstrapped"
        )
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
    is_decision_candidate = decision_candidate(strings)

    # Meaningful turn gate: a shard is ONLY written when tracked files changed.
    # Decision keyword matches alone are insufficient -- every discussion of this
    # system's own design would match, producing shards with no real content.
    if not files_touched:
        append_hook_trace(
            "Notify", "noop", repo_root=repo_root, details={"reason": "not_meaningful"}
        )
        emit_hook_response(
            "noop", message="notify payload was not meaningful; no shard written"
        )
        return 0

    # Determine which agent triggered this hook and resolve the model name.
    hook_event = find_first(payload, {"hook_event_name", "hookEventName"}) or ""
    is_claude_code = hook_event == "Stop" or bool(os.environ.get("CLAUDECODE"))

    if is_claude_code:
        # For Claude Code, read_claude_model() checks CLAUDE_MODEL env var first,
        # then falls back to ~/.claude/settings.json.  Never use read_codex_model()
        # for Claude Code sessions -- it would return the Codex model identifier instead.
        model = read_claude_model() or "claude-unknown"
    else:
        model = extract_model(payload)
        if not model:
            model = (
                "claude-unknown" if "stop" in hook_event.lower() else "agent-unknown"
            )
            warn(f"unable to resolve ai_model; defaulting to '{model}'")

    # Build shard identity fields.
    now = utc_now()
    timestamp = utc_timestamp(now)
    author = author_slug(repo_root)
    branch = current_branch(repo_root)
    thread_id = (
        find_first(payload, THREAD_KEYS) or stable_identifier("thread", payload)
    ).replace(" ", "_")

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
        find_first(payload, TURN_KEYS)
        or stable_identifier("turn", payload_for_turn_hash)
    ).replace(" ", "_")

    # Extract "why" text: prefer the user's prompt, fall back to the assistant response.
    prompt = find_first(payload, PROMPT_KEYS)
    if not prompt:
        transcript_path = payload.get("transcript_path") or payload.get(
            "transcriptPath"
        )
        if transcript_path:
            prompt = extract_user_prompt_from_transcript(str(transcript_path))

    assistant_text = find_first(payload, ASSISTANT_KEYS)
    why_lines = []
    if prompt:
        why_lines.append(f"- {prompt.strip()}")
    elif assistant_text:
        why_lines.append(f"- {assistant_text.strip().splitlines()[0]}")
    else:
        why_lines.append("- Meaningful repo state changed during this agent turn.")

    what_lines = [f"- Updated {path}" for path in files_touched] or [
        "- No tracked files were detected."
    ]
    evidence_lines = verification or [
        "- Tracked repo changes were detected in the working tree."
    ]
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

    # Assign agent attribution based on hook event name.
    if hook_event == "AfterAgent":
        ai_tool = "gemini"
        ai_surface = "gemini-cli"
        model = model or "gemini-unknown"
    elif hook_event == "Stop":
        ai_tool = "claude"
        ai_surface = "claude-code"
    else:
        ai_tool = "codex"
        ai_surface = "codex-cli"

    # Build the shard frontmatter.  OrderedDict preserves a stable field order
    # that is easier to scan in a Markdown viewer.
    metadata = OrderedDict(
        [
            ("timestamp", timestamp),
            ("author", author),
            ("branch", branch),
            ("thread_id", thread_id),
            ("turn_id", turn_id),
            ("decision_candidate", is_decision_candidate),
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
    run(
        [
            str(Path(__file__).with_name("rebuild-summary.py")),
            "--repo-root",
            str(repo_root),
            "--date",
            timestamp[:10],
        ],
        cwd=repo_root,
        check=True,
    )

    summary_path = day_dir / "summary.md"
    if not summary_path.exists():
        warn("summary rebuild did not produce summary.md")
        emit_hook_response(
            "error", message="summary rebuild did not produce summary.md"
        )
        return 1

    # Stage the shard and rebuilt summary so they are ready to commit alongside
    # the code changes.  The developer must commit explicitly -- this system
    # never auto-commits.
    stage_paths(
        repo_root,
        [shard_path.relative_to(repo_root), summary_path.relative_to(repo_root)],
    )
    append_hook_trace(
        "Notify",
        "success",
        repo_root=repo_root,
        details={
            "decision_candidate": is_decision_candidate,
            "files_touched": files_touched,
            "shard_path": str(shard_path.relative_to(repo_root)),
            "summary_path": str(summary_path.relative_to(repo_root)),
            "thread_id": thread_id,
            "turn_id": turn_id,
        },
    )
    info(f"wrote {shard_path.relative_to(repo_root)}")
    emit_hook_response(
        "ok",
        shard_path=str(shard_path.relative_to(repo_root)),
        summary_path=str(summary_path.relative_to(repo_root)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
