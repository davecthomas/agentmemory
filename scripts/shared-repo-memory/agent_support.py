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
        str_agent_id: Short machine identifier (e.g., "claude", "gemini", "codex").
        str_config_dir: User-home-relative config directory name (e.g., ".claude").
        dict_hook_event_map: Maps canonical hook names to the runtime's event
            names.  Keys are the canonical names used in this system
            (SessionStart, PostTurn, SubagentStop, PromptGuard, PostCompact);
            values are the runtime-specific event names.
        str_env_var: Environment variable set by the runtime, used for detection.
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
    str_agent_id: str
    str_config_dir: str
    dict_hook_event_map: dict[str, str]
    str_env_var: str
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
            str_agent_id="claude",
            str_config_dir=".claude",
            dict_hook_event_map={
                "SessionStart": "SessionStart",
                "PostTurn": "Stop",
                "SubagentStop": "SubagentStop",
                "PromptGuard": "UserPromptSubmit",
                "PostCompact": "PostCompact",
            },
            str_env_var="CLAUDECODE",
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
            str_agent_id="gemini",
            str_config_dir=".gemini",
            dict_hook_event_map={
                "SessionStart": "SessionStart",
                "PostTurn": "AfterAgent",
                "PromptGuard": "BeforeAgent",
            },
            str_env_var="GEMINI_CLI",
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
            str_agent_id="codex",
            str_config_dir=".codex",
            dict_hook_event_map={
                "SessionStart": "SessionStart",
            },
            str_env_var="",
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
    # Map AgentSupport boolean fields to human-readable hook labels.
    _CAPABILITY_LABELS: list[tuple[str, str]] = [
        ("bool_supports_session_start", "SessionStart"),
        ("bool_supports_post_turn", "post-turn"),
        ("bool_supports_subagent_capture", "subagent capture"),
        ("bool_supports_prompt_guard", "prompt guard"),
        ("bool_supports_post_compact", "post-compact"),
    ]

    list_str_summary_lines: list[str] = []
    for agent in list_agent_support():
        supported = [label for attr, label in _CAPABILITY_LABELS if getattr(agent, attr)]
        unsupported = [label for attr, label in _CAPABILITY_LABELS if not getattr(agent, attr)]

        if unsupported:
            str_line = (
                f"{agent.str_agent_name}: {', '.join(supported)} "
                f"{'is' if len(supported) == 1 else 'are'} supported. "
                f"{', '.join(unsupported).capitalize()} "
                f"{'is' if len(unsupported) == 1 else 'are'} unavailable."
            )
        else:
            str_line = (
                f"{agent.str_agent_name}: {', '.join(supported)} are supported."
            )

        # Append post-turn mode note for non-native runtimes.
        if agent.str_post_turn_mode != "native" and agent.bool_supports_post_turn is False:
            str_line += (
                " Native post-turn capture is not provisioned;"
                " notify-wrapper remains a manual smoke-test path."
            )

        list_str_summary_lines.append(str_line)
    return list_str_summary_lines
