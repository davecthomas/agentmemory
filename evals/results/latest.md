# Eval 2026-09-05T1845Z

Model: `default` · runs per call: 1 · memory context 1467 words (≈1907 tokens) · legacy context 1748 words from `29a591a`

| Question | none | legacy | memory |
|---|---:|---:|---:|
| storage-location | 0.00 | 1.00 | 1.00 |
| no-service | 0.00 | 1.00 | 0.67 |
| opt-in | 0.00 | 0.00 | 1.00 |
| capture-unit | 0.00 | 0.25 | 1.00 |
| commit-capture-rule | 0.00 | 0.00 | 1.00 |
| adr-only-durable | 0.00 | 1.00 | 1.00 |
| session-context | 0.00 | 0.75 | 1.00 |
| post-compact | 0.00 | 1.00 | 1.00 |
| catchup | 0.00 | 1.00 | 1.00 |
| runtime-support | 0.00 | 1.00 | 1.00 |
| no-auto-commit | 0.50 | 1.00 | 1.00 |
| query-path | 0.00 | 0.67 | 1.00 |
| holdout-black-pin (hold-out) | 0.50 | 0.50 | 0.50 |
| holdout-runtime-detection (hold-out) | 0.00 | 1.00 | 1.00 |
| holdout-uninstall-safety (hold-out) | 1.00 | 1.00 | 1.00 |
| holdout-quality-gate (hold-out) | 0.67 | 1.00 | 1.00 |
| holdout-hook-json (hold-out) | 0.00 | 1.00 | 1.00 |
| holdout-codex-symlink (hold-out) | 0.50 | 0.50 | 1.00 |
| **mean (keyword)** | **0.18** | **0.76** | **0.95** |

Keyword score is `must_mention` coverage; judge score is an isolated `claude -p` grading against each question's `expected` answer. Hold-out questions were written from git history and AGENTS.md rather than from the ADRs.
