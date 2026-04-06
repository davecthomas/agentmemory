#!/usr/bin/env python3
"""agent_support.py -- Canonical support declarations for each agent runtime.

This module centralizes the currently supported hook surface for Claude Code,
Gemini CLI, and Codex CLI. The goal is not to implement per-agent behavior
here; it is to provide one explicit source of truth for what is supported today
so installers, docs, and future adapters do not drift.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSupport:
    """Describe the supported hook surface for one agent runtime.

    Args:
        str_agent_name: Human-readable runtime name used in logs and docs.
        bool_supports_session_start: True when the runtime supports loading
            memory at session open.
        bool_supports_post_turn: True when post-turn shard capture is a
            supported native runtime feature.
        bool_supports_subagent_capture: True when subagent or task-agent turns
            can also emit shards through a dedicated hook.
        bool_supports_prompt_guard: True when the runtime supports the
            empty-memory bootstrap nudge before a user turn.
        bool_supports_post_compact: True when the runtime supports re-injecting
            memory after context compaction.
        str_post_turn_mode: Short label describing how post-turn capture is
            delivered today, such as "native" or "manual wrapper only".
        str_notes: Operator-facing note about important support limitations.
    """

    str_agent_name: str
    bool_supports_session_start: bool
    bool_supports_post_turn: bool
    bool_supports_subagent_capture: bool
    bool_supports_prompt_guard: bool
    bool_supports_post_compact: bool
    str_post_turn_mode: str
    str_notes: str


def list_agent_support() -> list[AgentSupport]:
    """Return the canonical support declarations for all supported runtimes.

    Returns:
        list[AgentSupport]: Ordered support metadata for Claude Code, Gemini
            CLI, and Codex CLI. The values describe the current intended
            product surface rather than speculative future support.
    """
    list_agent_support_entries: list[AgentSupport] = [
        AgentSupport(
            str_agent_name="Claude Code",
            bool_supports_session_start=True,
            bool_supports_post_turn=True,
            bool_supports_subagent_capture=True,
            bool_supports_prompt_guard=True,
            bool_supports_post_compact=True,
            str_post_turn_mode="native",
            str_notes="Primary runtime with the full supported hook surface.",
        ),
        AgentSupport(
            str_agent_name="Gemini CLI",
            bool_supports_session_start=True,
            bool_supports_post_turn=True,
            bool_supports_subagent_capture=False,
            bool_supports_prompt_guard=True,
            bool_supports_post_compact=False,
            str_post_turn_mode="native",
            str_notes=(
                "Supported for SessionStart, prompt guard, and post-turn capture. "
                "No subagent-stop or post-compact equivalent."
            ),
        ),
        AgentSupport(
            str_agent_name="Codex CLI",
            bool_supports_session_start=True,
            bool_supports_post_turn=False,
            bool_supports_subagent_capture=False,
            bool_supports_prompt_guard=False,
            bool_supports_post_compact=False,
            str_post_turn_mode="manual wrapper only",
            str_notes=(
                "Supported for SessionStart only. Repo-local notify-wrapper "
                "smoke tests exist, but native post-turn capture is not a "
                "supported provisioned path."
            ),
        ),
    ]
    return list_agent_support_entries


def support_summary_lines() -> list[str]:
    """Render concise human-readable support summary lines for installers.

    Returns:
        list[str]: One summary line per runtime, suitable for install logs and
            validation output. Each line explicitly calls out major support
            limits so degraded runtimes are visible to operators.
    """
    list_str_summary_lines: list[str] = []
    list_agent_support_entries: list[AgentSupport] = list_agent_support()
    for agent_support in list_agent_support_entries:
        if agent_support.str_agent_name == "Claude Code":
            str_line: str = (
                "Claude Code: SessionStart, post-turn, subagent capture, "
                "prompt guard, and post-compact are supported."
            )
        elif agent_support.str_agent_name == "Gemini CLI":
            str_line = (
                "Gemini CLI: SessionStart, post-turn, and prompt guard are "
                "supported. Subagent capture and post-compact are unavailable."
            )
        else:
            str_line = (
                "Codex CLI: SessionStart only. Native post-turn capture is not "
                "provisioned; notify-wrapper remains a manual smoke-test path."
            )
        list_str_summary_lines.append(str_line)
    return list_str_summary_lines
