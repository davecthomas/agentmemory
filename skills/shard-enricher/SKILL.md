---
name: shard-enricher
description: Rewrites a raw mechanical event shard with semantically meaningful content distilled from agent reasoning.
license: MIT
---

# Enrich Raw Event Shard

## Keywords

enrich, shard, memory, semantic, rewrite, decision candidate

## When to Use This Skill

- An event shard was just written by the post-turn hook with mechanical placeholder content
- An enrichment context JSON file exists containing the assistant's reasoning text
- You need to distill agent reasoning into durable, architecturally meaningful memory

This skill is invoked automatically by the post-turn hook as a fire-and-forget subagent. It can also be invoked manually to re-enrich a shard.

---

## Task Format

When invoked automatically, the task message contains:

```
Enrich the shard using context at: <absolute path to context JSON>
```

## Context JSON Schema

The context file contains:

- `shard_path`: absolute path to the raw shard to overwrite
- `repo_root`: absolute path to the repository
- `assistant_text`: the agent's response from the turn (the richest signal)
- `prompt`: the user's task that drove the changes
- `files_touched`: which files changed
- `diff_summary`: compact git diff output

## Workflow

### 1. Read the context JSON file

Read the file at the path provided in the task message. Understand the full context of what happened during the turn.

### 2. Distill semantic content from the assistant text

The `assistant_text` field contains the agent's reasoning -- this is the richest signal for understanding *why* changes were made. The `prompt` provides the user's intent. The `diff_summary` and `files_touched` provide concrete evidence.

### 3. Call enrich-shard.py with enriched content

```bash
python3 $HOME/.agent/shared-repo-memory/enrich-shard.py <context-json-path> \
    --why "<enriched why>" \
    --what "<enriched what>" \
    --evidence "<enriched evidence>" \
    --next "<enriched next>" \
    [--decision-candidate]
```

## Section Content Guidelines

- **--why**: 1-3 sentences about WHY this change matters architecturally. Not a restatement of the diff. Focus on intent, motivation, and significance.
- **--what**: Semantic summary of what was done. Purpose and impact, not filenames.
- **--evidence**: Concrete signals -- test results, design doc alignment, architectural choices made.
- **--next**: Genuine follow-up work, unresolved issues, or architectural implications.
- **--decision-candidate**: Include this flag ONLY if the turn involved a durable architectural decision (architecture boundaries, API contracts, tool choices, accepted tradeoffs, invariants). Do not flag routine implementation work.

## Example Invocation

```bash
python3 $HOME/.agent/shared-repo-memory/enrich-shard.py /path/to/context.json \
    --why "Extracted runtime-specific behavior into adapter modules to keep the core memory engine agent-neutral, following the design doc's separation of concerns." \
    --what "Introduced AgentAdapter protocol with concrete implementations for Claude, Gemini, and Codex. Moved payload normalization, response rendering, and hook wiring out of entrypoints into adapter modules." \
    --evidence "All 57 existing tests pass. Adapter pattern matches the target architecture in docs/agent-runtime-adapter-refactor-plan.md." \
    --next "prompt-guard.py still uses manual payload parsing. Design doc auto-generation from capability registry (step 5) not yet implemented." \
    --decision-candidate
```

## Quality Constraints

- Keep each section concise (1-5 bullet points or sentences).
- Do not dump raw assistant text into sections.
- The Why section must explain motivation, not restate the diff or list filenames.
- Evidence must cite concrete signals, not vague claims.
- Only flag decision_candidate when the turn genuinely involved an architectural choice that future agents need to know about.
