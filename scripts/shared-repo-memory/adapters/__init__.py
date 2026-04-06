#!/usr/bin/env python3
"""adapters -- Runtime adapter package for the shared repo-memory system.

Each agent runtime (Claude Code, Gemini CLI, Codex CLI) has a concrete adapter
that implements the AgentAdapter protocol.  Core memory logic calls adapter
methods to handle runtime-specific concerns such as:

  - Environment-based runtime detection
  - Hook payload normalization into canonical models
  - Response rendering in the runtime's expected JSON schema
  - AI model resolution from env vars and config files
  - Shard attribution (ai_tool, ai_surface)
  - Installer hook wiring
  - Subagent bootstrap command construction

Public API:
  detect_adapter()                -- detect from env vars (SessionStart, etc.)
  detect_adapter_from_hook_event  -- detect from hook_event payload field (post-turn)
  AgentAdapter                    -- typing protocol all adapters implement
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from models import HookRequest, HookResponse, SessionResponse, ShardAttribution


@dataclass
class InstallerContext:
    """Shared state passed to adapter.wire_hooks() during installation.

    Attributes:
        install_root: Directory where scripts are installed (e.g., ~/.agent/shared-repo-memory/).
        home: User home directory.
        repo_root: Absolute path to the agentmemory repository root.
        dry_run: When True, log actions without making changes.
        load_json: Callable to load a JSON file, returning {} on missing/corrupt.
        save_json: Callable to persist a dict as pretty-printed JSON.
    """

    install_root: Path
    home: Path
    repo_root: Path
    dry_run: bool
    load_json: Any  # Callable[[Path], dict]
    save_json: Any  # Callable[[Path, dict], None]


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that every agent runtime adapter must implement.

    Adapters are stateless; all methods are classmethods or take explicit
    arguments so they can be used without instantiation.
    """

    @staticmethod
    def agent_id() -> str:
        """Return the short machine identifier (e.g., 'claude', 'gemini', 'codex')."""
        ...

    @staticmethod
    def matches_environment() -> bool:
        """Return True when environment variables indicate this runtime is active."""
        ...

    @staticmethod
    def matches_hook_event(hook_event: str) -> bool:
        """Return True when the hook event name belongs to this runtime."""
        ...

    @staticmethod
    def normalize_hook_request(raw: dict[str, Any]) -> HookRequest:
        """Parse a raw stdin JSON dict into a canonical HookRequest."""
        ...

    @staticmethod
    def render_session_response(resp: SessionResponse) -> str:
        """Serialize a SessionResponse to the JSON string expected by this runtime."""
        ...

    @staticmethod
    def render_hook_response(resp: HookResponse) -> str:
        """Serialize a HookResponse to the JSON string expected by this runtime."""
        ...

    @staticmethod
    def resolve_model(payload: dict[str, Any]) -> str:
        """Return the AI model identifier from the payload, env vars, or config files."""
        ...

    @staticmethod
    def shard_attribution() -> ShardAttribution:
        """Return the agent identity fields for shard frontmatter."""
        ...

    @staticmethod
    def wire_hooks(ctx: InstallerContext) -> None:
        """Write agent-specific hook configuration during installation."""
        ...

    @staticmethod
    def build_bootstrap_command(
        skill_content: str, task: str, repo_root: Path
    ) -> list[str] | None:
        """Return the CLI command to spawn a subagent for memory bootstrap.

        Returns None if this runtime cannot spawn subagents.
        """
        ...

    @staticmethod
    def timeout_value(seconds: int) -> int:
        """Convert a timeout in seconds to this runtime's expected unit."""
        ...


# ---- Registry ---------------------------------------------------------------

# Import order matters: Claude is checked first, then Gemini, then Codex (fallback).
from adapters.claude import ClaudeAdapter  # noqa: E402
from adapters.codex import CodexAdapter  # noqa: E402
from adapters.gemini import GeminiAdapter  # noqa: E402

_ADAPTERS: list[type[AgentAdapter]] = [ClaudeAdapter, GeminiAdapter, CodexAdapter]


def detect_adapter() -> type[AgentAdapter]:
    """Detect the active runtime from environment variables.

    Checks adapters in priority order (Claude, Gemini, Codex) and returns the
    first whose matches_environment() returns True.  Falls back to CodexAdapter
    when no env var matches, since Codex is the only runtime without a detection
    env var.  Callers that need a bootstrap command should handle the case where
    the adapter returns None from build_bootstrap_command().
    """
    for adapter in _ADAPTERS:
        if adapter.matches_environment():
            return adapter
    return CodexAdapter


def detect_adapter_from_hook_event(hook_event: str) -> type[AgentAdapter]:
    """Detect the active runtime from the hook event name in the payload.

    Used primarily by post-turn-notify.py where the hook_event field is the
    most reliable signal (e.g., "Stop" for Claude, "AfterAgent" for Gemini).
    Falls back to environment-based detection when no adapter claims the event.
    """
    for adapter in _ADAPTERS:
        if adapter.matches_hook_event(hook_event):
            return adapter
    return detect_adapter()


__all__ = [
    "AgentAdapter",
    "InstallerContext",
    "ClaudeAdapter",
    "GeminiAdapter",
    "CodexAdapter",
    "detect_adapter",
    "detect_adapter_from_hook_event",
]
