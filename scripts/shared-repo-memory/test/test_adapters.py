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

import adapters  # noqa: E402
from adapters import (  # noqa: E402
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
    InstallerContext,
    UnknownAdapter,
    detect_adapter,
    detect_adapter_from_hook_event,
)
from common import (  # noqa: E402
    SHARED_REPO_MEMORY_SYSTEM_VERSION,
    append_hook_trace,
    clear_runtime_log_context,
    format_log_prefix,
    set_runtime_log_context,
)
from models import HookResponse, SessionResponse  # noqa: E402

# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    "CLAUDECODE",
    "GEMINI_CLI",
    "CODEX_THREAD_ID",
    "CODEX_SHELL",
    "CODEX_CI",
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "__CFBundleIdentifier",
)


def _empty_runtime_env() -> dict[str, str]:
    """Return a copy of os.environ with every runtime-discovery key stripped."""
    return {k: v for k, v in os.environ.items() if k not in _RUNTIME_ENV_KEYS}


class TestDetectAdapter:
    def setup_method(self):
        # _detect_runtime_from_process_tree is @cache'd, so clear between tests
        # to ensure each test controls detection deterministically.
        adapters._detect_runtime_from_process_tree.cache_clear()

    def test_claude_env_var(self):
        env = _empty_runtime_env()
        env["CLAUDECODE"] = "1"
        with patch.dict(os.environ, env, clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter() is ClaudeAdapter

    def test_gemini_env_var(self):
        env = _empty_runtime_env()
        env["GEMINI_CLI"] = "1"
        with patch.dict(os.environ, env, clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter() is GeminiAdapter

    def test_codex_env_var(self):
        env = _empty_runtime_env()
        env["CODEX_THREAD_ID"] = "thread-abc"
        with patch.dict(os.environ, env, clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter() is CodexAdapter

    def test_no_signal_returns_unknown(self):
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter() is UnknownAdapter

    def test_claude_takes_priority_over_gemini(self):
        env = _empty_runtime_env()
        env["CLAUDECODE"] = "1"
        env["GEMINI_CLI"] = "1"
        with patch.dict(os.environ, env, clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter() is ClaudeAdapter

    def test_payload_transcript_path_detects_claude(self):
        """Claude-shaped payload wins even when CLAUDECODE is absent."""
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert (
                detect_adapter({"transcript_path": "/tmp/t.jsonl"}) is ClaudeAdapter
            )

    def test_payload_stop_event_detects_claude(self):
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert detect_adapter({"hook_event_name": "Stop"}) is ClaudeAdapter

    def test_payload_after_agent_detects_gemini(self):
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert (
                detect_adapter({"hook_event_name": "AfterAgent"}) is GeminiAdapter
            )

    def test_payload_takes_priority_over_env(self):
        """Claude-fingerprint payload beats a stale GEMINI_CLI env var."""
        env = _empty_runtime_env()
        env["GEMINI_CLI"] = "1"
        with patch.dict(os.environ, env, clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            assert (
                detect_adapter({"transcript_path": "/tmp/t.jsonl"}) is ClaudeAdapter
            )

    def test_ambiguous_session_start_falls_through_to_process_tree(self):
        """SessionStart alone is ambiguous; process tree must resolve it."""
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value="claude"
        ):
            assert detect_adapter({"hook_event_name": "SessionStart"}) is ClaudeAdapter

    def test_process_tree_detects_runtime_without_env_var(self):
        """This is the chuckclose regression: Claude Code hook with no CLAUDECODE."""
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value="claude"
        ):
            assert detect_adapter() is ClaudeAdapter

    def test_process_tree_detects_codex(self):
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value="codex"
        ):
            assert detect_adapter() is CodexAdapter


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

    def test_unknown_event_falls_back_to_detect_adapter(self):
        adapters._detect_runtime_from_process_tree.cache_clear()
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            # No adapter claims empty string; no env, no process tree, no
            # payload -> UnknownAdapter rather than silently picking Codex.
            assert detect_adapter_from_hook_event("") is UnknownAdapter

    def test_unknown_event_with_payload_resolves_via_payload(self):
        adapters._detect_runtime_from_process_tree.cache_clear()
        with patch.dict(os.environ, _empty_runtime_env(), clear=True), patch.object(
            adapters, "_detect_runtime_from_process_tree", return_value=None
        ):
            result = detect_adapter_from_hook_event(
                "", {"transcript_path": "/tmp/t.jsonl"}
            )
            assert result is ClaudeAdapter


# ---------------------------------------------------------------------------
# Payload fingerprint tests
# ---------------------------------------------------------------------------


class TestMatchesPayload:
    def test_claude_transcript_path_snake(self):
        assert ClaudeAdapter.matches_payload({"transcript_path": "/tmp/t.jsonl"})

    def test_claude_transcript_path_camel(self):
        assert ClaudeAdapter.matches_payload({"transcriptPath": "/tmp/t.jsonl"})

    def test_claude_stop_event(self):
        assert ClaudeAdapter.matches_payload({"hook_event_name": "Stop"})

    def test_claude_subagent_stop_event(self):
        assert ClaudeAdapter.matches_payload({"hookEventName": "SubagentStop"})

    def test_claude_session_start_alone_is_ambiguous(self):
        """SessionStart is shared across runtimes; not a Claude-unique marker."""
        assert not ClaudeAdapter.matches_payload({"hook_event_name": "SessionStart"})

    def test_claude_empty_transcript_does_not_match(self):
        assert not ClaudeAdapter.matches_payload({"transcript_path": ""})

    def test_claude_empty_payload_does_not_match(self):
        assert not ClaudeAdapter.matches_payload({})

    def test_gemini_after_agent(self):
        assert GeminiAdapter.matches_payload({"hook_event_name": "AfterAgent"})

    def test_gemini_before_agent(self):
        assert GeminiAdapter.matches_payload({"hookEventName": "BeforeAgent"})

    def test_gemini_session_start_alone_is_ambiguous(self):
        assert not GeminiAdapter.matches_payload({"hook_event_name": "SessionStart"})

    def test_gemini_empty_payload_does_not_match(self):
        assert not GeminiAdapter.matches_payload({})

    def test_codex_has_no_unique_payload_fingerprint(self):
        """Codex relies on env vars and process ancestry, not payload shape."""
        assert not CodexAdapter.matches_payload({"hook_event_name": "SessionStart"})
        assert not CodexAdapter.matches_payload({})


# ---------------------------------------------------------------------------
# Process-tree detection tests
# ---------------------------------------------------------------------------


class TestProcessTreeDetection:
    def setup_method(self):
        adapters._detect_runtime_from_process_tree.cache_clear()

    def teardown_method(self):
        adapters._detect_runtime_from_process_tree.cache_clear()

    def test_matches_direct_parent(self):
        def fake_parent_comm(pid: int):
            # Parent of current process is "claude".
            return (1, "claude")

        with patch.object(adapters, "_parent_comm", side_effect=fake_parent_comm):
            assert adapters._detect_runtime_from_process_tree() == "claude"

    def test_matches_grandparent(self):
        # Parent is a shim (bash), grandparent is claude.
        call_order = iter(
            [
                (500, "bash"),
                (1, "claude"),
            ]
        )

        def fake_parent_comm(pid: int):
            return next(call_order)

        with patch.object(adapters, "_parent_comm", side_effect=fake_parent_comm):
            assert adapters._detect_runtime_from_process_tree() == "claude"

    def test_returns_none_when_no_match_in_chain(self):
        def fake_parent_comm(pid: int):
            return (1, "bash")

        with patch.object(adapters, "_parent_comm", side_effect=fake_parent_comm):
            # Every ancestor is bash; after the bounded walk returns None.
            adapters._detect_runtime_from_process_tree.cache_clear()
            assert adapters._detect_runtime_from_process_tree() is None

    def test_returns_none_when_ps_unavailable(self):
        with patch.object(adapters, "_parent_comm", return_value=None):
            assert adapters._detect_runtime_from_process_tree() is None

    def test_stops_at_init(self):
        """Walk must terminate at pid 0 or self-loop (pid == ppid)."""
        calls = iter([(0, "launchd")])
        with patch.object(adapters, "_parent_comm", side_effect=lambda p: next(calls)):
            assert adapters._detect_runtime_from_process_tree() is None


# ---------------------------------------------------------------------------
# UnknownAdapter tests
# ---------------------------------------------------------------------------


class TestUnknownAdapter:
    def test_agent_id(self):
        assert UnknownAdapter.agent_id() == "unknown"

    def test_detection_contracts(self):
        assert UnknownAdapter.matches_environment() is False
        assert UnknownAdapter.matches_hook_event("Stop") is False
        assert UnknownAdapter.matches_payload({"hook_event_name": "Stop"}) is False

    def test_cannot_bootstrap(self):
        assert (
            UnknownAdapter.build_bootstrap_command("skill", "task", Path("/tmp"))
            is None
        )

    def test_shard_attribution_is_unknown(self):
        attr = UnknownAdapter.shard_attribution()
        assert attr.ai_tool == "unknown"
        assert attr.ai_surface == "unknown"

    def test_renders_valid_session_json(self):
        resp = SessionResponse(system_message="ok")
        output = json.loads(UnknownAdapter.render_session_response(resp))
        assert output["systemMessage"] == "ok"


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
        cmd = ClaudeAdapter.build_bootstrap_command(
            "skill text", "Bootstrap.", Path("/repo")
        )
        assert cmd is not None
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--system-prompt" in cmd
        assert "skill text" in cmd
        assert "--cwd" not in cmd
        assert "Bootstrap." in cmd

    def test_gemini_command(self):
        cmd = GeminiAdapter.build_bootstrap_command(
            "skill text", "Bootstrap.", Path("/repo")
        )
        assert cmd is not None
        assert cmd[0] == "gemini"
        assert "--prompt" in cmd
        assert "--system-prompt" in cmd

    def test_codex_returns_none(self):
        cmd = CodexAdapter.build_bootstrap_command(
            "skill text", "Bootstrap.", Path("/repo")
        )
        assert cmd is None


class TestCodexHookWiring:
    def test_codex_hook_commands_quote_script_paths(self, tmp_path: Path):
        home_dir: Path = tmp_path / "home"
        install_root: Path = home_dir / ".agent" / "shared repo memory"
        repo_root: Path = tmp_path / "authoring repo"

        def load_json(path_json: Path) -> dict[str, object]:
            if not path_json.exists():
                return {}
            return json.loads(path_json.read_text(encoding="utf-8"))

        def save_json(path_json: Path, payload: dict[str, object]) -> None:
            path_json.parent.mkdir(parents=True, exist_ok=True)
            path_json.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        install_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        context = InstallerContext(
            install_root=install_root,
            home=home_dir,
            repo_root=repo_root,
            dry_run=False,
            load_json=load_json,
            save_json=save_json,
        )

        CodexAdapter.wire_hooks(context)

        hooks_path: Path = home_dir / ".codex" / "hooks.json"
        hooks_payload: dict[str, object] = json.loads(
            hooks_path.read_text(encoding="utf-8")
        )
        dict_hooks: dict[str, object] = hooks_payload["hooks"]
        list_session_start_hooks: list[object] = dict_hooks["SessionStart"]
        dict_session_start_group: dict[str, object] = list_session_start_hooks[0]
        list_session_start_commands: list[object] = dict_session_start_group["hooks"]
        dict_session_start_command: dict[str, object] = list_session_start_commands[0]
        list_prompt_guard_hooks: list[object] = dict_hooks["UserPromptSubmit"]
        dict_prompt_guard_group: dict[str, object] = list_prompt_guard_hooks[0]
        list_prompt_guard_commands: list[object] = dict_prompt_guard_group["hooks"]
        dict_prompt_guard_command: dict[str, object] = list_prompt_guard_commands[0]

        assert (
            dict_session_start_command["command"]
            == "python3 '" + str(install_root / "session-start.py") + "'"
        )
        assert (
            dict_prompt_guard_command["command"]
            == "python3 '" + str(install_root / "prompt-guard.py") + "'"
        )


class TestRuntimeLogMetadata:
    def teardown_method(self):
        clear_runtime_log_context()

    def test_format_log_prefix_uses_explicit_context(self):
        set_runtime_log_context("codex", "0.118.0")
        assert format_log_prefix() == (
            f"[agentmemory][version={SHARED_REPO_MEMORY_SYSTEM_VERSION}]"
            "[runtime=codex][runtime-version=0.118.0]"
        )

    def test_append_hook_trace_includes_runtime_metadata(self, tmp_path: Path):
        with patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=False):
            set_runtime_log_context("gemini", "0.36.0")
            append_hook_trace("Notify", "success")

        trace_path: Path = (
            tmp_path / ".agent" / "state" / "shared-repo-memory-hook-trace.jsonl"
        )
        payload: dict[str, object] = json.loads(
            trace_path.read_text(encoding="utf-8").splitlines()[0]
        )
        assert payload["runtime"] == "gemini"
        assert payload["runtime_version"] == "0.36.0"
