#!/usr/bin/env python3
"""models.py -- Normalized request/response models for agent hook payloads.

These dataclasses decouple core memory logic from the agent-specific payload
formats emitted by Claude Code, Gemini CLI, and Codex CLI.  Adapter modules
translate raw hook JSON into these models; entrypoint scripts work exclusively
with the normalized forms.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HookRequest:
    """Canonical representation of an incoming agent hook payload.

    Adapters parse raw stdin JSON into this model so that core logic never
    inspects agent-specific key names directly.

    Attributes:
        hook_event: Agent-reported hook event name (e.g., "Stop", "AfterAgent").
        session_id: Conversation or session identifier, if available.
        thread_id: Thread identifier used to group turns into a conversation.
        turn_id: Individual turn identifier within the thread.
        cwd: Working directory at hook invocation time.
        prompt: User prompt text that triggered the turn.
        assistant_text: Most recent assistant response text.
        model: AI model identifier resolved from the payload or environment.
        transcript_path: Path to the JSONL transcript file, if available.
        raw: Original unmodified payload dict for fallback field lookups.
    """

    hook_event: str = ""
    session_id: str = ""
    thread_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    prompt: str = ""
    assistant_text: str = ""
    model: str = ""
    transcript_path: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookResponse:
    """Canonical response payload for post-turn and general hook events.

    Attributes:
        status: Short status token: "ok", "noop", "error", "skipped".
        message: Optional human-readable description of the status.
        extra: Additional key-value pairs merged into the JSON response.
    """

    status: str = "ok"
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionResponse:
    """Canonical response payload for SessionStart hooks.

    Attributes:
        system_message: Short status text shown in the agent UI.
        additional_context: Memory text injected into the model context before
            the first turn.
        continue_session: When False, signals the agent to abort the session.
    """

    system_message: str = ""
    additional_context: str = ""
    continue_session: bool = True


@dataclass(frozen=True)
class ShardAttribution:
    """Agent identity fields written into event shard frontmatter.

    Attributes:
        ai_tool: Tool identifier (e.g., "claude", "gemini", "codex").
        ai_surface: Surface identifier (e.g., "claude-code", "gemini-cli").
        default_model: Fallback model name when the payload lacks one.
    """

    ai_tool: str = ""
    ai_surface: str = ""
    default_model: str = ""
