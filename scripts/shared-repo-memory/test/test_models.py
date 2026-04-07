#!/usr/bin/env python3
"""test_models.py -- Tests for the normalized request/response models."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models import (  # noqa: E402
    HookRequest,
    HookResponse,
    SessionResponse,
    ShardAttribution,
)


class TestHookRequest:
    def test_defaults(self):
        req = HookRequest()
        assert req.hook_event == ""
        assert req.thread_id == ""
        assert req.raw == {}

    def test_frozen(self):
        req = HookRequest(hook_event="Stop")
        with pytest.raises(AttributeError):
            req.hook_event = "Other"  # type: ignore[misc]

    def test_all_fields(self):
        req = HookRequest(
            hook_event="Stop",
            session_id="s1",
            thread_id="t1",
            turn_id="u1",
            cwd="/repo",
            prompt="Fix bug",
            assistant_text="Fixed.",
            model="claude-sonnet-4-6",
            transcript_path="/tmp/t.jsonl",
            raw={"key": "value"},
        )
        assert req.hook_event == "Stop"
        assert req.session_id == "s1"
        assert req.raw == {"key": "value"}


class TestHookResponse:
    def test_defaults(self):
        resp = HookResponse()
        assert resp.status == "ok"
        assert resp.message == ""
        assert resp.extra == {}

    def test_frozen(self):
        resp = HookResponse(status="noop")
        with pytest.raises(AttributeError):
            resp.status = "ok"  # type: ignore[misc]


class TestSessionResponse:
    def test_defaults(self):
        resp = SessionResponse()
        assert resp.system_message == ""
        assert resp.additional_context == ""
        assert resp.continue_session is True

    def test_abort(self):
        resp = SessionResponse(continue_session=False)
        assert resp.continue_session is False


class TestShardAttribution:
    def test_fields(self):
        attr = ShardAttribution(
            ai_tool="claude", ai_surface="claude-code", default_model="claude-unknown"
        )
        assert attr.ai_tool == "claude"
        assert attr.ai_surface == "claude-code"
        assert attr.default_model == "claude-unknown"

    def test_frozen(self):
        attr = ShardAttribution()
        with pytest.raises(AttributeError):
            attr.ai_tool = "gemini"  # type: ignore[misc]
