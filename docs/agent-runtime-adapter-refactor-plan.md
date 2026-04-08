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

## Shard quality: two-phase enrichment via subagent

### Problem

Event shards produced by `post-turn-notify.py` are mechanically generated from `git diff` output and regex pattern matching. The resulting content restates what is already visible in the commit history and provides no architectural insight, no reasoning about *why* changes matter, and no useful context for future agents or developers. The `assistant_text` field is extracted from every hook payload but never used.

Regex-based extraction cannot produce semantic understanding. Only an LLM can distill an agent's reasoning into meaningful, durable memory.

### Architecture: two-phase shard write

**Phase 1 (synchronous, in Stop/AfterAgent hook):** Write a raw shard with mechanical data (frontmatter, files_touched, user prompt) under `pending/` and save an enrichment context file containing `assistant_text`, prompt, diff summary, and shard paths. Return immediately with zero added latency. Do not rebuild summaries in this phase.

**Phase 2 (async, fire-and-forget):** Spawn a subagent via the detected adapter's CLI as a background subprocess. The subagent reads the enrichment context, produces semantically enriched shard content, publishes the final shard under `daily/`, rebuilds the daily summary once after publish, deletes the corresponding pending shard, and then deletes the ephemeral context file.

### Multi-runtime subagent enrichment

Enrichment uses `adapter.build_bootstrap_command()` with the same fallback chain as memory bootstrap:

| Runtime | Subagent command | Auth | Status |
|---------|-----------------|------|--------|
| Claude Code | `claude -p --system-prompt <skill> --cwd <repo> <task>` | Keychain/OAuth | Full support |
| Gemini CLI | `gemini --prompt <task> --system-prompt <skill>` | Gemini auth | Full support |
| Codex CLI | Falls back to Claude CLI | Keychain/OAuth | Degraded -- post-turn hooks not reliably firing as of Codex release 117; revisit when a future release improves hook support |

When the detected adapter returns `None` from `build_bootstrap_command()`, the system falls back to `ClaudeAdapter.build_bootstrap_command()` before giving up.

### What the enrichment subagent produces

The subagent replaces the four body sections of the raw shard:

- **Why**: 1-3 sentences distilling user intent and agent reasoning into *why this change matters* architecturally. Not a restatement of the diff.
- **What changed**: Semantic summary of what was done -- purpose and impact, not filenames.
- **Evidence**: Concrete signals -- test results, design doc alignment, specific architectural choices made.
- **Next**: Genuine follow-up work, unresolved issues, or architectural implications.

Existing frontmatter is otherwise preserved, but enrichment may update system-managed frontmatter fields such as `decision_candidate` and `enriched`. The substantive content change is limited to the four body sections above.

### Graceful degradation

- No subagent CLI available: pending raw shard stays local-only and unpublished.
- Enrichment subprocess fails or crashes: pending raw shard remains local-only.
- Empty assistant_text (Codex manual wrapper, truncated payloads): enrich from diff + prompt only, or skip enrichment entirely.
- Summary is rebuilt only after publish, so the durable read model changes atomically with the published shard.

### Enrichment-based decision candidate detection

The current `decision_candidate()` function in `post-turn-notify.py` uses a regex gate:

    pattern = r"\b(decision|policy|contract|standard|repo rule|adr|must read|governing)\b"

This never fires in practice because developers do not narrate their architectural choices with these keywords during normal work. After four days of active development including a major platform refactor, zero shards were flagged as decision candidates.

The enrichment subagent replaces this. When enriching a shard, the subagent evaluates whether the turn involved an architectural decision and sets `decision_candidate: true` or `false` in the enriched shard. The raw shard defaults to `false` as a safe pre-enrichment value.

### Design constraints

- No external API keys required. Subagent CLIs use their own auth (keychain, OAuth).
- No latency added to the hook. Enrichment is fully asynchronous.
- One enrichment attempt per shard. No retry loops.
- Enrichment context files are ephemeral (dot-prefixed, deleted after use, never committed).
- Adding a new runtime adapter automatically gets enrichment support through the adapter protocol.

## ADR promotion: design doc inspection

### Problem

Design docs are the richest source of ADR-worthy decisions, but nothing inspects them. The existing ADR promotion pipeline depends entirely on event shards being flagged `decision_candidate: true`, which requires the regex gate described above. Since that gate never fires, no ADRs are ever promoted from live work. All six existing ADRs came from bootstrap.

Even if the shard enrichment fix resolves the `decision_candidate` detection problem for turn-level work, it misses the most important ADR source: design docs themselves. When an agent writes or updates a document like `docs/agent-runtime-adapter-refactor-plan.md`, the decisions recorded there should be inspected for ADR promotion independently of the event shard pipeline.

### Architecture: design doc ADR inspection

When `post-turn-notify.py` detects that `files_touched` includes a design doc (matching patterns such as `docs/*`, `*design*`, `*spec*`, `*arch*`, `*adr*`), it spawns a separate async subagent task in addition to normal shard writing and enrichment.

#### Skill: `adr-inspector`

The inspection subagent is driven by a new skill installed at `~/.agent/skills/adr-inspector/SKILL.md`. The skill file serves as the system prompt for the subagent, following the same pattern as `memory-bootstrap`.

`post-turn-notify.py` spawns the subagent via `adapter.build_bootstrap_command(skill_content, task, repo_root)` where:
- `skill_content` is the contents of `adr-inspector/SKILL.md`
- `task` identifies the changed design doc paths and the repo root

The skill instructs the subagent to:

1. Read the changed design doc(s) at the paths provided in the task.
2. Read the existing ADR index (`.agents/memory/adr/INDEX.md`) and existing ADR files to understand what decisions are already captured.
3. Identify decisions in the design doc that are ADR-worthy but not yet recorded.
4. For each new decision: write a decision-candidate shard under `.agents/memory/daily/<today>/events/` with `decision_candidate: true` and rich semantic content derived from the design doc.
5. Call `promote-adr.py` to promote each candidate shard to a full ADR.
6. Stage the new shard(s) and ADR file(s) via `git add`.

The skill source file lives in the repo at `skills/adr-inspector/SKILL.md` and is installed to `~/.agent/skills/adr-inspector/` by `install.py`, with per-agent symlinks under `~/.claude/skills/`, `~/.gemini/skills/`, and `~/.codex/skills/` (same installation pattern as all other skills).

#### Trigger and independence

Design doc inspection runs independently of shard enrichment. A single turn that changes a design doc fires both processes: shard enrichment (for the turn's own shard) and design doc inspection (for ADR candidates found in the document). The two subagent processes do not coordinate; they write to different files and do not conflict.

### What makes a decision ADR-worthy

The inspection subagent uses the same selection criteria proven by `auto-bootstrap.py`:

Favor:
- architecture boundaries and layer separation
- canonical data sources and ownership
- API contracts and interface decisions
- tool and dependency choices with rationale
- output conventions and format standards
- accepted tradeoffs with explicit reasoning
- invariants and constraints

Reject:
- tasks and rollout sequencing
- local optimizations without systemic impact
- implementation trivia

### Multi-runtime support

Design doc inspection uses the same `adapter.build_bootstrap_command()` pattern and fallback chain as shard enrichment and memory bootstrap.

### Relationship to existing ADR promotion

ADR-0005 established that ADR promotion is always explicit and separate from post-turn capture. Design doc inspection respects this boundary: it creates decision-candidate shards and promotes them through the existing `promote-adr.py` pathway rather than writing ADR files directly. The promotion step remains auditable and traceable through the shard-to-ADR link.

## New files introduced by these changes

| File | Purpose |
|------|---------|
| `scripts/shared-repo-memory/enrich-shard.py` | Standalone enrichment script invoked by subagent to rewrite raw shard body sections |
| `skills/adr-inspector/SKILL.md` | Skill defining the system prompt for the design doc ADR inspection subagent |

## Suggested migration sequence

1. Extract the capability registry into the shared core.
2. Introduce normalized request and response models for SessionStart and post-turn capture.
3. Move installer wiring into per-agent adapter modules.
4. Move payload parsing and hook response rendering into per-agent adapter modules.
5. Convert docs and doctor output to render from the capability registry.
6. Add adapter-specific test suites before removing the old mixed logic.
7. Add two-phase shard enrichment via subagent to post-turn-notify.py.
8. Replace regex-based decision candidate detection with enrichment-based semantic evaluation.
9. Create `skills/adr-inspector/SKILL.md` and add design doc ADR inspection as an async subagent task triggered by design doc changes in post-turn-notify.py.
10. Add shard enrichment and design doc inspection capability flags to agent_support.py.
11. Update install.py to install enrich-shard.py and the adr-inspector skill.
