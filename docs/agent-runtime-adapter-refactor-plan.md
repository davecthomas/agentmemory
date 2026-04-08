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

## Memory trust: pending captures plus workstream checkpoints

### Problem

Publishing one durable shard per file-changing turn is the wrong trust boundary.

Single turns often do not contain enough context to explain the larger issue being
advanced, the subsystem or architectural surface affected, and the concrete
outcome of that turn in the context of the broader effort. When the system tries
to publish directly from one turn anyway, the result is low-signal memory:
diff restatements, filename lists, or mechanically paraphrased fragments with no
gestalt.

The privacy boundary is also too weak if raw prompt text or raw assistant text is
persisted on disk. Durable repo memory must never enshrine direct user wording,
and local-only staging data should avoid persisting raw conversation content when
repo-grounded context is sufficient.

### Product invariant

Published memory must be:

- coherent at the workstream level, not merely the single-turn level
- privacy-safe, with no direct user prompt text persisted or published
- fail-closed: no shard is better than a bad shard

This changes the model from **turn enrichment** to **workstream checkpoint
publication**.

### Terminology

To avoid repeating the old mistake in new code and docs, the unit names should
stay explicit:

- `turn`: one prompt-response interaction or hook event; useful provenance only
- `file-changing turn`: a turn whose working-tree effects touched repo files
- `pending capture`: one local-only mechanical record written from one file-changing turn
- `workstream episode`: a bounded, semantically related set of pending captures
- `checkpoint`: the durable published memory synthesized from a workstream episode

Durable memory should be described in terms of episodes and checkpoints, not as
single-turn memory. A single turn can be mechanically important enough to
capture without being semantically whole enough to publish.

### Architecture: three-phase checkpoint pipeline

**Phase 1 (synchronous, in Stop/AfterAgent hook):** Write a local-only pending
capture under `pending/` with mechanical facts only: timestamp, branch, touched
files, diff summary, attribution, and stable identity metadata. Do not persist
raw user prompt text. Do not persist raw assistant text. Do not rebuild
summaries in this phase.

**Phase 2 (async, fire-and-forget):** Build an ephemeral checkpoint context
manifest that references a bounded workstream episode plus
supporting repo context such as touched design docs, ADR index, and recent
summaries. Spawn a background subagent via the detected adapter's CLI. The
subagent reads the referenced files, decides whether the episode supports a
durable checkpoint, and if so produces structured checkpoint fields.

**Phase 3 (local publish/validate):** A local publisher script validates the
structured checkpoint output. Only valid checkpoints are written to
`daily/<date>/events/`, summary rebuild runs once after publish, the published
artifacts are staged, and the consumed pending captures are deleted. When
validation fails or the subagent returns `publish: false`, nothing is published.

### What counts as a workstream episode

A workstream episode is a bounded set of related pending captures. The current
bundle selection rules should stay simple and deterministic:

- current pending capture is always included
- prefer same `thread_id` when the runtime provides one
- otherwise fall back to same branch, optionally narrowed by touched-file overlap
- include only a small recent window (for example, 3-7 pending captures)

This is a local-only read model used to give the subagent enough context to infer
the broader effort. It is not a committed artifact, and it is the semantic unit
that durable checkpoints are built from.

### Multi-runtime background checkpointing

Checkpoint evaluation uses `adapter.build_bootstrap_command()` with the same
fallback chain as memory bootstrap:

| Runtime | Subagent command | Auth | Status |
|---------|-----------------|------|--------|
| Claude Code | `claude -p --system-prompt <skill> <task>` | Keychain/OAuth | Full support |
| Gemini CLI | `gemini --prompt <task> --system-prompt <skill>` | Gemini auth | Full support |
| Codex CLI | Falls back to Claude CLI | Keychain/OAuth | Degraded -- native post-turn hooks are not yet a supported product path |

The parent process sets `cwd=<repo_root>` when launching the subprocess. The
command itself should not rely on a Claude-specific working-directory flag.

When the detected adapter returns `None` from `build_bootstrap_command()`, the
system falls back to `ClaudeAdapter.build_bootstrap_command()` before giving up.

### Structured checkpoint output

The background subagent must not emit free-form prose and trust the local
publisher to interpret it. Instead, it must return structured output that the
publisher can validate mechanically.

Minimum required fields:

- `publish`: boolean
- `workstream_goal`: the larger issue or goal being advanced
- `subsystem_surface`: the subsystem or architectural surface affected
- `turn_outcome`: the concrete outcome reached by the latest turn in that broader effort
- `why`: semantic rationale lines
- `what_changed`: semantic change lines
- `evidence`: concrete repo-grounded evidence lines
- `next`: follow-up or implications lines
- `decision_candidate`: boolean
- `source_pending_shards`: the pending captures consumed by this checkpoint

If the subagent cannot produce those fields coherently, it must return
`publish: false`.

### The gestalt gate

The local publisher enforces the key trust boundary:

- `workstream_goal`, `subsystem_surface`, and `turn_outcome` must all be present
- they must be distinct, not trivial paraphrases of each other
- together they must form one coherent synopsis of the broader issue, affected
  area, and concrete latest-turn contribution
- the four published body sections must align with that synopsis rather than
  restating diffs or filenames

This is the core reason the bundle exists at all: a single turn often lacks
enough information to satisfy the gestalt gate, while a short series of related
pending captures often does.

### Privacy and trust gates

The publish validator must reject output that violates any of these invariants:

- direct user prompt text or quoted prompt fragments
- raw assistant-response passthrough
- diff-stat restatements as durable memory
- filename-only or patch-summary-only content
- placeholder or boilerplate text with no repo-specific meaning
- malformed or incomplete section output

The simplest way to satisfy the privacy invariant is to avoid persisting prompt
text and raw assistant text in the pending capture or checkpoint context at all.

### Decision candidate detection moves to the checkpoint level

`decision_candidate` should no longer be inferred from a single turn's keyword
matches. Instead, the checkpoint subagent evaluates the whole workstream episode
and marks the published checkpoint as a decision candidate only when it captures
an actual durable architectural decision.

This keeps routine implementation turns from polluting the ADR pipeline while
still allowing a multi-turn design or refactor effort to promote durable
decisions once enough context exists.

### Graceful degradation

- No subagent CLI available: pending captures remain local-only.
- Insufficient context to explain the broader workstream: no publish.
- Validation fails: no publish.
- Concurrent evaluations race: only validations against still-present source
  pending captures may publish.

In all of these cases the system keeps raw local staging data, but durable
memory remains unchanged.

### Design constraints

- No external API keys required. Subagent CLIs use their own auth.
- No latency added to the hook. Bundling and checkpoint evaluation are asynchronous.
- Pending captures are local-only and must never be committed.
- Published memory remains plain Markdown under `.agents/memory/daily/`.
- The summary format and ADR workflow stay unchanged.

## ADR promotion: design doc inspection

### Problem

Design docs are the richest source of ADR-worthy decisions, but nothing inspects them. The existing ADR promotion pipeline depends entirely on event shards being flagged `decision_candidate: true`, which requires the regex gate described above. Since that gate never fires, no ADRs are ever promoted from live work. All six existing ADRs came from bootstrap.

Even if trusted checkpoint publication resolves the `decision_candidate` detection problem for turn-level work, it misses the most important ADR source: design docs themselves. When an agent writes or updates a document like `docs/agent-runtime-adapter-refactor-plan.md`, the decisions recorded there should be inspected for ADR promotion independently of the event shard pipeline.

### Architecture: design doc ADR inspection

When `post-turn-notify.py` detects that `files_touched` includes a design doc (matching patterns such as `docs/*`, `*design*`, `*spec*`, `*arch*`, `*adr*`), it spawns a separate async subagent task in addition to normal checkpoint capture and publication.

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

Design doc inspection runs independently of checkpoint publication. A single turn that changes a design doc fires both processes: checkpoint evaluation (for the turn's own durable memory, if any) and design doc inspection (for ADR candidates found in the document). The two subagent processes do not coordinate; they write to different files and do not conflict.

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

Design doc inspection uses the same `adapter.build_bootstrap_command()` pattern and fallback chain as checkpoint evaluation and memory bootstrap.

### Relationship to existing ADR promotion

ADR-0005 established that ADR promotion is always explicit and separate from post-turn capture. Design doc inspection respects this boundary: it creates decision-candidate shards and promotes them through the existing `promote-adr.py` pathway rather than writing ADR files directly. The promotion step remains auditable and traceable through the shard-to-ADR link.

## New files introduced by these changes

| File | Purpose |
|------|---------|
| `scripts/shared-repo-memory/publish-checkpoint.py` | Standalone validator/publisher script invoked by the checkpoint subagent to publish only trusted workstream checkpoints |
| `skills/memory-checkpointer/SKILL.md` | Skill defining the system prompt for the workstream checkpoint evaluation subagent |
| `skills/adr-inspector/SKILL.md` | Skill defining the system prompt for the design doc ADR inspection subagent |

## Suggested migration sequence

1. Extract the capability registry into the shared core.
2. Introduce normalized request and response models for SessionStart and post-turn capture.
3. Move installer wiring into per-agent adapter modules.
4. Move payload parsing and hook response rendering into per-agent adapter modules.
5. Convert docs and doctor output to render from the capability registry.
6. Add adapter-specific test suites before removing the old mixed logic.
7. Add pending capture plus background checkpoint evaluation to post-turn-notify.py.
8. Replace regex-based decision candidate detection with checkpoint-level semantic evaluation.
9. Create `skills/adr-inspector/SKILL.md` and add design doc ADR inspection as an async subagent task triggered by design doc changes in post-turn-notify.py.
10. Add checkpoint publication and design doc inspection capability flags to agent_support.py.
11. Update install.py to install publish-checkpoint.py, memory-checkpointer, and the adr-inspector skill.
