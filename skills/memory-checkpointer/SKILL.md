---
name: memory-checkpointer
description: Evaluates a bounded bundle of pending captures and publishes one durable shared-memory checkpoint only when the bundle supports a coherent, privacy-safe workstream summary.
license: MIT
---

# Publish A Trusted Workstream Checkpoint

## Keywords

memory checkpoint, workstream checkpoint, pending captures, shard publication, semantic memory, privacy-safe memory, fail-closed memory

## When to Use This Skill

- `post-turn-notify.py` has written a local-only pending capture and a checkpoint context JSON file
- You need to inspect a bounded series of related pending captures before deciding whether durable memory should be published
- The repository uses `.agents/memory/` as canonical shared repo memory

This skill is invoked automatically by the post-turn hook as a fire-and-forget background subagent. It may also be invoked manually for recovery or re-evaluation.

---

## CLI / Non-Interactive Mode

When this skill is invoked as a background subagent via `claude -p` or `gemini --prompt`:

- Do not emit user-facing commentary.
- Do not ask questions.
- Read the checkpoint context file and the referenced local files directly.
- If the bundle does **not** justify a trustworthy checkpoint, call:

```bash
python3 "$HOME/.agent/shared-repo-memory/publish-checkpoint.py" <context-json-path> \
    --skip-publish \
    --reason "<brief reason>"
```

- If the bundle **does** justify a trustworthy checkpoint, call:

```bash
python3 "$HOME/.agent/shared-repo-memory/publish-checkpoint.py" <context-json-path> \
    --workstream-goal "<broader issue or goal>" \
    --subsystem-surface "<affected subsystem or architectural surface>" \
    --turn-outcome "<concrete latest-turn outcome>" \
    --why "<Why section content>" \
    --what-changed "<What changed section content>" \
    --evidence "<Evidence section content>" \
    --next "<Next section content>" \
    --source-pending-shard "<absolute pending shard path>" \
    [--source-pending-shard "<absolute pending shard path>"] \
    [--decision-candidate]
```

Do not write `.agents/memory/daily/...` files directly. Only `publish-checkpoint.py` may publish durable memory.

---

## Task Format

When invoked automatically, the task message contains:

```text
Evaluate the workstream checkpoint bundle using context at: <absolute path to context JSON>
```

## Context JSON Schema

The context file contains only repo-grounded metadata. It must not contain raw user prompt text or raw assistant response text.

- `repo_root`: absolute path to the repository root
- `current_pending_shard`: absolute path to the pending capture created by the latest turn
- `pending_shard_paths`: absolute paths to the bounded related pending captures in this bundle
- `pending_bundle`: structured metadata for those pending captures
- `published_shard_path`: absolute path where the durable checkpoint should be written if publication succeeds
- `workstream_id`: stable local workstream identifier
- `workstream_scope`: `thread` or `branch`
- `branch`: current branch name
- `files_touched`: current-turn changed files
- `design_docs_touched`: current-turn changed design docs
- `diff_summary`: compact current-turn diff summary
- `adr_index_path`: absolute path to `.agents/memory/adr/INDEX.md`
- `recent_summary_paths`: absolute paths to the most recent daily summaries

---

## Publication Rule

The default outcome is **no publish**.

Only publish when you can explain the workstream at a durable level:

1. What larger issue or goal is being advanced?
2. What subsystem or architectural surface is affected?
3. What concrete outcome did the latest turn achieve inside that broader effort?

If you cannot answer all three clearly from the bundle plus repo-grounded evidence, do not publish.

No shard is better than a bad shard.

---

## Privacy Rule

- Never quote or paraphrase direct user prompt wording.
- Never pass through raw assistant text.
- Do not reconstruct conversation text from memory.
- Work only from the repo-grounded context file, pending captures, touched files, design docs, ADR index, summaries, and diffs you inspect locally.

If the available repo-grounded evidence is not enough, skip publication.

---

## Quality Rule

The output must be semantically whole across the broader issue. Reject the bundle when the best possible shard would still look like any of these:

- a diff-stat restatement
- a filename list
- a tiny patch fragment with no larger context
- placeholder prose such as "repo state changed" or "await checkpoint evaluation"
- a one-turn summary that cannot explain the broader effort

`workstream-goal`, `subsystem-surface`, and `turn-outcome` must be distinct, not three paraphrases of the same sentence.

---

## Section Guidance

- `--workstream-goal`: One concise sentence naming the broader effort or problem being advanced.
- `--subsystem-surface`: One concise sentence naming the architectural boundary, subsystem, or execution path affected.
- `--turn-outcome`: One concise sentence naming what this turn concretely achieved inside that larger effort.
- `--why`: Explain why the broader effort and this checkpoint matter. This should be durable context for a future agent, not a diff restatement.
- `--what-changed`: Summarize the meaningful implementation or design movement. Prefer purpose and system effect over filenames.
- `--evidence`: Cite concrete repo-grounded signals such as tests, design docs, validators, hooks, summaries, ADRs, or specific files when they materially ground the checkpoint.
- `--next`: State the most likely follow-up, risk, or open edge. Use `- None.` only when the bundle clearly closes out the thread.
- `--decision-candidate`: Include this flag only when the checkpoint captures a durable architectural decision that future contributors should be able to promote into an ADR.

---

## Source Selection

- Always include `current_pending_shard` in `--source-pending-shard`.
- Include earlier pending captures only when they are part of the same bounded workstream and they materially improve the checkpoint gestalt.
- Prefer the smallest bundle that still produces a trustworthy checkpoint.

If the bundle is branch-scoped, single-capture, and not grounded by a design doc, bias strongly toward `--skip-publish`.
