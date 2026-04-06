#!/usr/bin/env python3
"""codex.py -- Codex CLI runtime adapter.

Handles all Codex CLI-specific concerns.  Codex is the fallback runtime when
neither CLAUDECODE nor GEMINI_CLI environment variables are set.

Codex currently supports only SessionStart natively.  Post-turn shard capture
is available only via the manual notify-wrapper.sh script.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common import find_first
from models import HookRequest, HookResponse, SessionResponse, ShardAttribution

# Payload key aliases -- same broad set for resilience.
_THREAD_KEYS = {"thread_id", "threadId", "conversation_id", "conversationId", "session_id", "sessionId"}
_TURN_KEYS = {"turn_id", "turnId", "id"}
_PROMPT_KEYS = {"prompt", "user_prompt", "userPrompt", "inputText", "input_text"}
_ASSISTANT_KEYS = {
    "last_assistant_message", "lastAssistantMessage", "output_text",
    "summary_text", "reasoning_text", "prompt_response", "text", "content",
}


class CodexAdapter:
    """Adapter for Codex CLI runtime (fallback when no env var matches)."""

    @staticmethod
    def agent_id() -> str:
        return "codex"

    @staticmethod
    def matches_environment() -> bool:
        # Codex is the fallback -- it matches when nothing else does.
        # No dedicated CODEX env var exists today.
        return False

    @staticmethod
    def matches_hook_event(hook_event: str) -> bool:
        # Codex has no unique hook event names; it only fires SessionStart
        # and manual wrapper invocations that don't set a hook event.
        return False

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
        """Resolve model from payload, then fall back to ~/.codex/config.toml."""
        model = find_first(payload, {"model", "model_name", "modelName"})
        if model:
            return model
        config_path = Path.home() / ".codex" / "config.toml"
        if config_path.exists():
            match = re.search(
                r'^\s*model\s*=\s*"([^"]+)"',
                config_path.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                return match.group(1)
        return "codex-unknown"

    @staticmethod
    def shard_attribution() -> ShardAttribution:
        return ShardAttribution(
            ai_tool="codex",
            ai_surface="codex-cli",
            default_model="codex-unknown",
        )

    @staticmethod
    def wire_hooks(ctx: InstallerContext) -> None:  # noqa: F821
        """Wire Codex hooks by updating ~/.codex/config.toml and ~/.codex/hooks.json.

        config.toml is edited in-place using regex to preserve existing user
        configuration and comments.
        """
        codex_config = ctx.home / ".codex" / "config.toml"
        codex_hooks = ctx.home / ".codex" / "hooks.json"

        if ctx.dry_run:
            return

        codex_config.parent.mkdir(parents=True, exist_ok=True)
        codex_config.touch()
        text = codex_config.read_text(encoding="utf-8")

        def upsert(key: str, line: str) -> None:
            nonlocal text
            pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
            if pattern.search(text):
                text = pattern.sub(line, text, count=1)
            else:
                suffix = "" if not text or text.endswith("\n") else "\n"
                text = f"{text}{suffix}\n{line}\n"

        def append_if_missing(pat: str, line: str, comment: str = "") -> None:
            nonlocal text
            if re.search(pat, text, re.MULTILINE):
                return
            prefix = f"\n# {comment}\n" if comment else "\n"
            text += f"{prefix}{line}\n"

        upsert("experimental_use_hooks", "experimental_use_hooks = true")
        upsert("hooks_config_path", f'hooks_config_path = "{codex_hooks}"')
        append_if_missing(
            r"^\s*features\.codex_hooks\s*=",
            "features.codex_hooks = true",
            "Enable Codex hook execution so SessionStart can validate installed shared memory assets.",
        )
        append_if_missing(
            r"^\s*shared_repo_memory_configured\s*=",
            "shared_repo_memory_configured = true",
            "Enable automatic shared repo-memory startup checks and repo bootstrap in Git repositories.",
        )
        append_if_missing(
            r"^\s*shared_agent_assets_repo_path\s*=",
            f'shared_agent_assets_repo_path = "{ctx.repo_root}"',
            "Shared repo-memory authoring checkout used to refresh installed shared assets.",
        )

        escaped = re.escape(str(ctx.repo_root))
        if not re.search(rf'\[projects\."{escaped}"\]', text):
            text += (
                f"\n# Trust this shared repo-memory authoring repo for local Codex work.\n"
                f'[projects."{ctx.repo_root}"]\ntrust_level = "trusted"\n'
            )

        codex_config.write_text(text, encoding="utf-8")

        # Write hooks.json with SessionStart command.
        session_start_cmd = str(ctx.install_root / "session-start.py")
        hooks_data = ctx.load_json(codex_hooks)
        hooks_data.setdefault("hooks", {})
        hooks_data["hooks"]["SessionStart"] = [
            {
                "hooks": [
                    {"type": "command", "command": session_start_cmd, "timeout": 30}
                ]
            }
        ]
        ctx.save_json(codex_hooks, hooks_data)

    @staticmethod
    def build_bootstrap_command(
        skill_content: str, task: str, repo_root: Path
    ) -> list[str] | None:
        # Codex cannot spawn subagents for bootstrap.
        return None

    @staticmethod
    def timeout_value(seconds: int) -> int:
        return seconds
