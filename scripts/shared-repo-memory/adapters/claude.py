#!/usr/bin/env python3
"""claude.py -- Claude Code runtime adapter.

Handles all Claude Code-specific concerns: environment detection, payload
normalization, response rendering, model resolution, installer wiring, and
subagent bootstrap command construction.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from common import find_first
from models import HookRequest, HookResponse, SessionResponse, ShardAttribution

# Claude Code hook event names.
_HOOK_EVENTS = {
    "Stop",
    "SessionStart",
    "SubagentStop",
    "UserPromptSubmit",
    "PostCompact",
}

# Payload key aliases -- Claude Code uses camelCase and snake_case variants.
_THREAD_KEYS = {
    "thread_id",
    "threadId",
    "conversation_id",
    "conversationId",
    "session_id",
    "sessionId",
}
_TURN_KEYS = {"turn_id", "turnId", "id"}
_PROMPT_KEYS = {"prompt", "user_prompt", "userPrompt", "inputText", "input_text"}
_ASSISTANT_KEYS = {
    "last_assistant_message",
    "lastAssistantMessage",
    "output_text",
    "summary_text",
    "reasoning_text",
    "prompt_response",
    "text",
    "content",
}


class ClaudeAdapter:
    """Adapter for Claude Code runtime."""

    @staticmethod
    def agent_id() -> str:
        return "claude"

    @staticmethod
    def matches_environment() -> bool:
        return bool(os.environ.get("CLAUDECODE"))

    @staticmethod
    def matches_hook_event(hook_event: str) -> bool:
        return hook_event in _HOOK_EVENTS

    @staticmethod
    def normalize_hook_request(raw: dict[str, Any]) -> HookRequest:
        return HookRequest(
            hook_event=find_first(raw, {"hook_event_name", "hookEventName"}) or "",
            session_id=find_first(raw, {"session_id", "sessionId"}) or "",
            thread_id=find_first(raw, _THREAD_KEYS) or "",
            turn_id=find_first(raw, _TURN_KEYS) or "",
            cwd=find_first(raw, {"cwd", "workingDirectory"}) or "",
            prompt=find_first(raw, _PROMPT_KEYS) or "",
            assistant_text=find_first(raw, _ASSISTANT_KEYS) or "",
            model=find_first(raw, {"model", "model_name", "modelName"}) or "",
            transcript_path=find_first(raw, {"transcript_path", "transcriptPath"})
            or "",
            raw=raw,
        )

    @staticmethod
    def render_session_response(resp: SessionResponse) -> str:
        payload: dict[str, object] = {"systemMessage": resp.system_message}
        if not resp.continue_session:
            payload["continue"] = False
        if resp.additional_context:
            payload["hookSpecificOutput"] = {
                "hookEventName": "SessionStart",
                "additionalContext": resp.additional_context,
            }
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def render_hook_response(resp: HookResponse) -> str:
        payload: dict[str, Any] = {"status": resp.status}
        if resp.message:
            payload["message"] = resp.message
        for key, value in resp.extra.items():
            if value is not None:
                payload[key] = value
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def resolve_model(payload: dict[str, Any]) -> str:
        """Resolve model: CLAUDE_MODEL env var > ~/.claude/settings.json > payload."""
        model = os.environ.get("CLAUDE_MODEL")
        if model:
            return model
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                model = data.get("model")
                if model:
                    return model
            except (json.JSONDecodeError, OSError):
                pass
        return (
            find_first(payload, {"model", "model_name", "modelName"})
            or "claude-unknown"
        )

    @staticmethod
    def shard_attribution() -> ShardAttribution:
        return ShardAttribution(
            ai_tool="claude",
            ai_surface="claude-code",
            default_model="claude-unknown",
        )

    @staticmethod
    def wire_hooks(ctx: InstallerContext) -> None:  # noqa: F821
        """Wire Claude Code hooks by updating ~/.claude/settings.json."""

        session_start_cmd = str(ctx.install_root / "session-start.py")
        post_turn_cmd = str(ctx.install_root / "post-turn-notify.py")
        prompt_guard_cmd = str(ctx.install_root / "prompt-guard.py")
        post_compact_cmd = str(ctx.install_root / "post-compact.py")

        settings_path = ctx.home / ".claude" / "settings.json"
        settings = ctx.load_json(settings_path)
        settings["shared_repo_memory_configured"] = True
        settings["shared_agent_assets_repo_path"] = str(ctx.repo_root)

        hooks = settings.setdefault("hooks", {})

        # Each entry: (event_name, command_path, timeout_seconds)
        hook_specs = [
            ("SessionStart", session_start_cmd, 30),
            ("Stop", post_turn_cmd, 60),
            ("SubagentStop", post_turn_cmd, 60),
            ("UserPromptSubmit", prompt_guard_cmd, 10),
            ("PostCompact", post_compact_cmd, 15),
        ]

        for event_name, cmd, timeout in hook_specs:
            event_hooks = hooks.setdefault(event_name, [])
            already_wired = any(
                any(h.get("command") == cmd for h in entry.get("hooks", []))
                for entry in event_hooks
            )
            if not already_wired:
                event_hooks.append(
                    {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
                )

        ctx.save_json(settings_path, settings)

    @staticmethod
    def build_bootstrap_command(
        skill_content: str, task: str, repo_root: Path
    ) -> list[str] | None:
        return [
            "claude",
            "-p",
            "--system-prompt",
            skill_content,
            "--cwd",
            str(repo_root),
            task,
        ]

    @staticmethod
    def timeout_value(seconds: int) -> int:
        return seconds
