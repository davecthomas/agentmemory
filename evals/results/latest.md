# Eval 

Model: `default` · runs per call: 1 · memory context 1402 words (≈1822 tokens)

| Question | none | memory |
|---|---:|---:|
| storage-location | 0.00 | 1.00 |
| holdout-black-pin (hold-out) | 0.00 | 0.50 |
| **mean (keyword)** | **0.00** | **0.75** |
| mean (judge) | 0.00 | 0.42 |

Keyword score is `must_mention` coverage; judge score is an isolated `claude -p` grading against each question's `expected` answer. Hold-out questions were written from git history and AGENTS.md rather than from the ADRs.
