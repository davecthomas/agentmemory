#!/usr/bin/env python3
"""test_adapters.py -- Tests for the runtime adapter package.

Tests cover:
  - Environment-based runtime detection
  - Hook event-based detection
  - Payload normalization into HookRequest
  - Session and hook response rendering
  - Model resolution
  - Shard attribution
  - Timeout conversion
  - Bootstrap command construction
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the scripts directory is on sys.path so adapters and models can be imported.
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters import (  # noqa: E402
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
    detect_adapter,
    detect_adapter_from_hook_event,
)
from models import HookResponse, SessionResponse  # noqa: E402

# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDetectAdapter:
    def test_claude_env_var(self):
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            assert detect_adapter() is ClaudeAdapter

    def test_gemini_env_var(self):
        with patch.dict(os.environ, {"GEMINI_CLI": "1"}, clear=False):
            # Remove CLAUDECODE if present so Gemini wins
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            env["GEMINI_CLI"] = "1"
            with patch.dict(os.environ, env, clear=True):
                assert detect_adapter() is GeminiAdapter

    def test_fallback_is_claude(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "GEMINI_CLI")}
        with patch.dict(os.environ, env, clear=True):
            assert detect_adapter() is ClaudeAdapter

    def test_claude_takes_priority_over_gemini(self):
        with patch.dict(os.environ, {"CLAUDECODE": "1", "GEMINI_CLI": "1"}, clear=False):
            assert detect_adapter() is ClaudeAdapter


class TestDetectAdapterFromHookEvent:
    def test_stop_event_is_claude(self):
        assert detect_adapter_from_hook_event("Stop") is ClaudeAdapter

    def test_after_agent_is_gemini(self):
        assert detect_adapter_from_hook_event("AfterAgent") is GeminiAdapter

    def test_before_agent_is_gemini(self):
        assert detect_adapter_from_hook_event("BeforeAgent") is GeminiAdapter

    def test_session_start_is_claude(self):
        # Claude claims SessionStart (checked first in priority order)
        assert detect_adapter_from_hook_event("SessionStart") is ClaudeAdapter

    def test_unknown_event_falls_back_to_env(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "GEMINI_CLI")}
        with patch.dict(os.environ, env, clear=True):
            # No adapter claims empty string, falls back to env-based detection
            result = detect_adapter_from_hook_event("")
            assert result is ClaudeAdapter  # fallback


# ---------------------------------------------------------------------------
# Agent ID tests
# ---------------------------------------------------------------------------


class TestAgentId:
    def test_claude_id(self):
        assert ClaudeAdapter.agent_id() == "claude"

    def test_gemini_id(self):
        assert GeminiAdapter.agent_id() == "gemini"

    def test_codex_id(self):
        assert CodexAdapter.agent_id() == "codex"


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------


class TestNormalizeHookRequest:
    def test_claude_payload(self):
        raw = {
            "hookEventName": "Stop",
            "threadId": "abc-123",
            "turnId": "turn-1",
            "prompt": "Fix the bug",
            "lastAssistantMessage": "Done.",
            "model": "claude-sonnet-4-6",
            "transcriptPath": "/tmp/transcript.jsonl",
        }
        req = ClaudeAdapter.normalize_hook_request(raw)
        assert req.hook_event == "Stop"
        assert req.thread_id == "abc-123"
        assert req.turn_id == "turn-1"
        assert req.prompt == "Fix the bug"
        assert req.assistant_text == "Done."
        assert req.model == "claude-sonnet-4-6"
        assert req.transcript_path == "/tmp/transcript.jsonl"
        assert req.raw is raw

    def test_gemini_payload(self):
        raw = {
            "hookEventName": "AfterAgent",
            "conversation_id": "gem-456",
            "id": "turn-2",
            "input_text": "Add tests",
            "output_text": "Added tests.",
        }
        req = GeminiAdapter.normalize_hook_request(raw)
        assert req.hook_event == "AfterAgent"
        assert req.thread_id == "gem-456"
        assert req.turn_id == "turn-2"
        assert req.prompt == "Add tests"
        assert req.assistant_text == "Added tests."

    def test_codex_payload_with_snake_case(self):
        raw = {
            "hook_event_name": "SessionStart",
            "session_id": "sess-789",
            "conversation_id": "conv-100",
            "turn_id": "u-50",
            "user_prompt": "Refactor auth",
        }
        req = CodexAdapter.normalize_hook_request(raw)
        assert req.hook_event == "SessionStart"
        assert req.session_id == "sess-789"
        # find_first searches alias set including session_id; conversation_id is
        # also in the thread key set, so thread_id resolves to whichever is found first.
        assert req.thread_id in ("sess-789", "conv-100")
        assert req.turn_id == "u-50"
        assert req.prompt == "Refactor auth"

    def test_empty_payload(self):
        req = ClaudeAdapter.normalize_hook_request({})
        assert req.hook_event == ""
        assert req.thread_id == ""
        assert req.raw == {}


# ---------------------------------------------------------------------------
# Response rendering tests
# ---------------------------------------------------------------------------


class TestRenderSessionResponse:
    def test_basic_response(self):
        resp = SessionResponse(system_message="ok", additional_context="memory text")
        output = json.loads(ClaudeAdapter.render_session_response(resp))
        assert output["systemMessage"] == "ok"
        assert output["hookSpecificOutput"]["additionalContext"] == "memory text"
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "continue" not in output

    def test_abort_response(self):
        resp = SessionResponse(system_message="error", continue_session=False)
        output = json.loads(ClaudeAdapter.render_session_response(resp))
        assert output["continue"] is False
        assert "hookSpecificOutput" not in output

    def test_no_context(self):
        resp = SessionResponse(system_message="ok")
        output = json.loads(ClaudeAdapter.render_session_response(resp))
        assert "hookSpecificOutput" not in output

    def test_all_adapters_produce_same_schema(self):
        resp = SessionResponse(system_message="ok", additional_context="ctx")
        for adapter in [ClaudeAdapter, GeminiAdapter, CodexAdapter]:
            output = json.loads(adapter.render_session_response(resp))
            assert "systemMessage" in output
            assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"


class TestRenderHookResponse:
    def test_ok_response(self):
        resp = HookResponse(status="ok", message="shard written")
        output = json.loads(ClaudeAdapter.render_hook_response(resp))
        assert output == {"status": "ok", "message": "shard written"}

    def test_noop_with_extra(self):
        resp = HookResponse(
            status="noop", message="nothing to do", extra={"reason": "no_changes"}
        )
        output = json.loads(GeminiAdapter.render_hook_response(resp))
        assert output["status"] == "noop"
        assert output["reason"] == "no_changes"

    def test_none_extras_omitted(self):
        resp = HookResponse(status="ok", extra={"keep": "yes", "drop": None})
        output = json.loads(CodexAdapter.render_hook_response(resp))
        assert output.get("keep") == "yes"
        assert "drop" not in output


# ---------------------------------------------------------------------------
# Shard attribution tests
# ---------------------------------------------------------------------------


class TestShardAttribution:
    def test_claude_attribution(self):
        attr = ClaudeAdapter.shard_attribution()
        assert attr.ai_tool == "claude"
        assert attr.ai_surface == "claude-code"
        assert attr.default_model == "claude-unknown"

    def test_gemini_attribution(self):
        attr = GeminiAdapter.shard_attribution()
        assert attr.ai_tool == "gemini"
        assert attr.ai_surface == "gemini-cli"
        assert attr.default_model == "gemini-unknown"

    def test_codex_attribution(self):
        attr = CodexAdapter.shard_attribution()
        assert attr.ai_tool == "codex"
        assert attr.ai_surface == "codex-cli"
        assert attr.default_model == "codex-unknown"


# ---------------------------------------------------------------------------
# Model resolution tests
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_claude_env_var_priority(self):
        with patch.dict(os.environ, {"CLAUDE_MODEL": "claude-opus-4-6"}):
            model = ClaudeAdapter.resolve_model({})
            assert model == "claude-opus-4-6"

    def test_claude_payload_fallback(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            model = ClaudeAdapter.resolve_model({"model": "claude-sonnet-4-6"})
            assert model == "claude-sonnet-4-6"

    def test_claude_default(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            model = ClaudeAdapter.resolve_model({})
            assert model == "claude-unknown"

    def test_gemini_from_payload(self):
        model = GeminiAdapter.resolve_model({"model": "gemini-2.5-pro"})
        assert model == "gemini-2.5-pro"

    def test_gemini_default(self):
        model = GeminiAdapter.resolve_model({})
        assert model == "gemini-unknown"

    def test_codex_from_payload(self):
        model = CodexAdapter.resolve_model({"model_name": "o3-pro"})
        assert model == "o3-pro"


# ---------------------------------------------------------------------------
# Timeout conversion tests
# ---------------------------------------------------------------------------


class TestTimeoutValue:
    def test_claude_passthrough(self):
        assert ClaudeAdapter.timeout_value(30) == 30

    def test_gemini_to_milliseconds(self):
        assert GeminiAdapter.timeout_value(30) == 30000

    def test_codex_passthrough(self):
        assert CodexAdapter.timeout_value(60) == 60


# ---------------------------------------------------------------------------
# Bootstrap command tests
# ---------------------------------------------------------------------------


class TestBuildBootstrapCommand:
    def test_claude_command(self):
        cmd = ClaudeAdapter.build_bootstrap_command("skill text", "Bootstrap.", Path("/repo"))
        assert cmd is not None
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--system" in cmd
        assert "skill text" in cmd
        assert str(Path("/repo")) in cmd
        assert "Bootstrap." in cmd

    def test_gemini_command(self):
        cmd = GeminiAdapter.build_bootstrap_command("skill text", "Bootstrap.", Path("/repo"))
        assert cmd is not None
        assert cmd[0] == "gemini"
        assert "--prompt" in cmd
        assert "--system-prompt" in cmd

    def test_codex_returns_none(self):
        cmd = CodexAdapter.build_bootstrap_command("skill text", "Bootstrap.", Path("/repo"))
        assert cmd is None
