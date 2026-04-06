# Agent Runtime Adapter Refactor Plan

## Why this exists

The shared-memory system now has real runtime-specific behavior for Claude Code, Gemini CLI, and Codex CLI. Today that behavior is still manageable, but the coupling points are already visible:

- installers know too much about per-agent config layout
- runtime entrypoints mix shared-memory logic with agent-specific payload and hook details
- docs can drift from actual support if each runtime is described by hand

This document records the intended refactor direction so a future PR can separate the agent-specific surfaces cleanly without rediscovering the design.

## Big idea

Keep the shared-memory engine agent-neutral. Push runtime-specific behavior behind small agent adapters.

That means:

- core code owns memory semantics
- adapters own runtime semantics
- entrypoint scripts become thin orchestration layers

## Target architecture

### 1. Shared core

The core layer should own the durable product behavior that is the same regardless of runtime:

- repo bootstrap rules
- shard meaning and write rules
- summary rebuild logic
- catch-up rebuild logic
- memory bootstrap policy
- support capability declarations

The core should not know Claude hook names, Gemini matcher syntax, or Codex config file quirks.

### 2. Agent adapters

Each runtime gets a focused adapter module:

- `claude`
- `gemini`
- `codex`

Each adapter should own:

- config file locations
- supported hook events
- payload normalization into a shared request model
- response rendering in that runtime's accepted schema
- installer wiring for that runtime
- validation and doctor output for that runtime

### 3. Thin entrypoints

Scripts such as `session-start.py`, `post-turn-notify.py`, and `prompt-guard.py` should mostly do four things:

1. read stdin and environment
2. identify the active runtime
3. normalize the request through the runtime adapter
4. call shared core logic and render the runtime-specific response

## Foundational design implications

### Capability declarations must be authoritative

The support matrix should live in code, not only in docs. Installer output, validation messaging, and docs should all derive from the same capability declaration.

### Degraded support must stay explicit

If a runtime lacks a stable supported hook surface, the system should say so directly rather than papering over it with fragile workarounds.

### Repo-local and user-level concerns should stay separate

Repo bootstrap should remain about repo-owned state such as `.agents/memory/`, `.githooks/`, and local catch-up files. User-global installer logic should remain responsible for runtime config files under home directories.

### Manual wrappers are not product support

Utility wrappers such as `notify-wrapper.sh` can remain valuable for smoke tests and debugging, but they should not be described as supported runtime integrations unless the installer provisions them and validation enforces them.

### Tests should split by layer

Future tests should separate:

- core behavior tests
- adapter contract tests
- end-to-end runtime wiring tests

That split will make it easier to change one runtime without destabilizing the whole system.

## Non-goals for the future refactor

The refactor should not change:

- the canonical memory location under `.agents/memory/`
- the shard format
- the summary format
- the explicit ADR promotion workflow

Those are product contracts, not runtime adapter details.

## Suggested migration sequence

1. Extract the capability registry into the shared core.
2. Introduce normalized request and response models for SessionStart and post-turn capture.
3. Move installer wiring into per-agent adapter modules.
4. Move payload parsing and hook response rendering into per-agent adapter modules.
5. Convert docs and doctor output to render from the capability registry.
6. Add adapter-specific test suites before removing the old mixed logic.
