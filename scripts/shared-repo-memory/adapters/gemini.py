#!/usr/bin/env python3
"""gemini.py -- Gemini CLI runtime adapter.

Handles all Gemini CLI-specific concerns: environment detection, payload
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

# Gemini CLI hook event names.
_HOOK_EVENTS = {"SessionStart", "AfterAgent", "BeforeAgent"}

# Payload key aliases -- same broad set for resilience.
_THREAD_KEYS = {"thread_id", "threadId", "conversation_id", "conversationId", "session_id", "sessionId"}
_TURN_KEYS = {"turn_id", "turnId", "id"}
_PROMPT_KEYS = {"prompt", "user_prompt", "userPrompt", "inputText", "input_text"}
_ASSISTANT_KEYS = {
    "last_assistant_message", "lastAssistantMessage", "output_text",
    "summary_text", "reasoning_text", "prompt_response", "text", "content",
}


class GeminiAdapter:
    """Adapter for Gemini CLI runtime."""

    @staticmethod
    def agent_id() -> str:
        return "gemini"

    @staticmethod
    def matches_environment() -> bool:
        return bool(os.environ.get("GEMINI_CLI"))

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
            transcript_path=find_first(raw, {"transcript_path", "transcriptPath"}) or "",
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
        """Resolve model from payload keys."""
        model = find_first(payload, {"model", "model_name", "modelName"})
        return model or "gemini-unknown"

    @staticmethod
    def shard_attribution() -> ShardAttribution:
        return ShardAttribution(
            ai_tool="gemini",
            ai_surface="gemini-cli",
            default_model="gemini-unknown",
        )

    @staticmethod
    def wire_hooks(ctx: InstallerContext) -> None:  # noqa: F821
        """Wire Gemini CLI hooks by updating ~/.gemini/settings.json.

        Gemini uses "matcher" fields and named hooks for idempotency detection.
        Timeouts are in milliseconds.
        """
        session_start_cmd = str(ctx.install_root / "session-start.py")
        post_turn_cmd = str(ctx.install_root / "post-turn-notify.py")
        prompt_guard_cmd = str(ctx.install_root / "prompt-guard.py")

        settings_path = ctx.home / ".gemini" / "settings.json"
        settings = ctx.load_json(settings_path)
        settings["shared_agent_assets_repo_path"] = str(ctx.repo_root)
        settings["shared_repo_memory_configured"] = True

        hooks = settings.setdefault("hooks", {})

        # Each entry: (event_name, hook_name, command_path, timeout_ms)
        hook_specs = [
            ("SessionStart", "shared-repo-memory-session-start", session_start_cmd, 30000),
            ("AfterAgent", "shared-repo-memory-post-turn", post_turn_cmd, 30000),
            ("BeforeAgent", "shared-repo-memory-prompt-guard", prompt_guard_cmd, 10000),
        ]

        for event_name, hook_name, cmd, timeout_ms in hook_specs:
            event_hooks = hooks.setdefault(event_name, [])
            already_wired = any(
                h.get("matcher") == "*"
                and any(sh.get("name") == hook_name for sh in h.get("hooks", []))
                for h in event_hooks
            )
            if not already_wired:
                event_hooks.append({
                    "matcher": "*",
                    "hooks": [{
                        "name": hook_name,
                        "type": "command",
                        "command": cmd,
                        "timeout": timeout_ms,
                    }],
                })

        ctx.save_json(settings_path, settings)

    @staticmethod
    def build_bootstrap_command(
        skill_content: str, task: str, repo_root: Path
    ) -> list[str] | None:
        return [
            "gemini",
            "--prompt", task,
            "--system-prompt", skill_content,
        ]

    @staticmethod
    def timeout_value(seconds: int) -> int:
        return seconds * 1000
