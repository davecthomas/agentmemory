#!/usr/bin/env python3
"""Measure whether decision memory helps a fresh session answer repo questions.

Each question in ``questions.json`` is asked of ``claude -p`` with tools
disabled, so the answer can come only from the prompt, in two conditions:

* ``none``: the bare question
* ``memory``: the question preceded by the session-start context block from
  ``session-start.py --print-context``
* ``legacy``: the question preceded by what v0.4 injected, the ADR index
  plus the three newest daily summaries, read from ``--legacy-ref``
  (default ``main``) so the rebuild is measured against what it replaced

Both run from an empty temporary directory with a replaced system prompt
and no dynamic sections, so Claude Code loads no CLAUDE.md, AGENTS.md,
per-project auto-memory, or installed skill descriptions; the prompt is
the only source of repo knowledge in either condition.

Score is the fraction of ``must_mention`` terms present in the answer (a
nested list counts when any alternative matches). The run prints a table,
writes ``evals/results/<timestamp>.json``, and exits 1 when the memory
condition does not beat the no-memory condition on average. ``--dry-run``
prints the prompts and skips the model.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE: Path = Path(__file__).resolve().parent
SCRIPTS: Path = HERE.parent / "scripts" / "shared-repo-memory"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402

DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash",
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Agent",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "TodoWrite",
    "Skill",
)
SYSTEM_PROMPT: str = (
    "You are answering questions about a software repository. Answer only "
    "from the information in the prompt. Be concrete and name files, flags, "
    "and mechanisms. If the prompt gives you nothing on the topic, say so "
    "in one sentence."
)


def score(answer: str, must_mention: list[Any]) -> tuple[float, list[str]]:
    """Score one answer.

    Args:
        answer: Model output.
        must_mention: Terms; a nested list is satisfied by any member.

    Returns:
        tuple[float, list[str]]: Coverage in [0, 1] and the missed terms.
    """
    low: str = answer.lower()
    missed: list[str] = []
    for term in must_mention:
        options: list[str] = term if isinstance(term, list) else [term]
        if not any(o.lower() in low for o in options):
            missed.append(" | ".join(options))
    return (1 - len(missed) / len(must_mention)) if must_mention else 1.0, missed


def memory_block(root: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "session-start.py"),
            "--print-context",
            "--repo-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def legacy_block(root: Path, ref: str) -> str:
    """Rebuild the v0.4 session-start block from a git ref.

    Args:
        root: Repository root.
        ref: Commit or branch holding the v0.4 memory tree.

    Returns:
        str: ADR index plus up to three newest daily summaries, or ``""``.
    """
    sections: list[str] = []
    index: str = common.git(["show", f"{ref}:.agents/memory/adr/INDEX.md"], root)
    if index:
        sections.append("### Architecture Decision Records\n\n" + index)
    listing: str = common.git(
        ["ls-tree", "-r", "--name-only", ref, "--", ".agents/memory/daily"], root
    )
    summaries: list[str] = sorted(
        (p for p in listing.splitlines() if p.endswith("/summary.md")), reverse=True
    )[:3]
    for path in summaries:
        day: str = path.split("/")[-2]
        sections.append(
            f"### Memory: {day}\n\n" + common.git(["show", f"{ref}:{path}"], root)
        )
    return "\n\n".join(sections)


def ask(prompt: str, *, model: str | None, cwd: Path, timeout: int) -> str:
    cmd: list[str] = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--system-prompt",
        SYSTEM_PROMPT,
        "--exclude-dynamic-system-prompt-sections",
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]
    if model:
        cmd += ["--model", model]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env={**os.environ, "AGENTMEMORY_DISABLED": "1"},
    )
    if result.returncode != 0:
        return f"[claude exited {result.returncode}: {result.stderr.strip()[:300]}]"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()
    return str(payload.get("result", result.stdout)).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--questions", default=str(HERE / "questions.json"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=0, help="first N questions only")
    parser.add_argument("--only", default=None, help="comma-separated question ids")
    parser.add_argument("--conditions", default="none,legacy,memory")
    parser.add_argument("--legacy-ref", default="main")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = common.repo_root(args.repo_root)
    if root is None:
        print("run_eval: not inside a git repository", file=sys.stderr)
        return 1
    questions: list[dict[str, Any]] = json.loads(Path(args.questions).read_text())[
        "questions"
    ]
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]
    conditions: list[str] = [c.strip() for c in args.conditions.split(",") if c.strip()]
    context: str = memory_block(root) if "memory" in conditions else ""
    if "memory" in conditions and not context:
        print(
            "run_eval: repo has no memory context; nothing to measure", file=sys.stderr
        )
        return 1
    legacy: str = legacy_block(root, args.legacy_ref) if "legacy" in conditions else ""
    if "legacy" in conditions and not legacy:
        print(
            f"run_eval: no v0.4 memory at {args.legacy_ref}; dropping legacy",
            file=sys.stderr,
        )
        conditions = [c for c in conditions if c != "legacy"]

    rows: list[dict[str, Any]] = []
    neutral = Path(tempfile.mkdtemp(prefix="agentmemory-eval-"))
    for q in questions:
        row: dict[str, Any] = {"id": q["id"], "question": q["question"], "results": {}}
        for cond in conditions:
            prompt: str = q["question"]
            if cond == "memory":
                prompt = f"Repository decision memory:\n\n{context}\n\n---\n\nQuestion: {q['question']}"
            elif cond == "legacy":
                prompt = f"Repository decision memory:\n\n{legacy}\n\n---\n\nQuestion: {q['question']}"
            if args.dry_run:
                row["results"][cond] = {
                    "score": None,
                    "prompt_words": common.word_count(prompt),
                }
                continue
            started = time.time()
            answer: str = ask(
                prompt, model=args.model, cwd=neutral, timeout=args.timeout
            )
            value, missed = score(answer, q["must_mention"])
            row["results"][cond] = {
                "score": round(value, 3),
                "missed": missed,
                "seconds": round(time.time() - started, 1),
                "answer": answer,
            }
            print(
                f"{q['id']:<22} {cond:<7} {value:5.2f}  missed: {', '.join(missed) or '-'}",
                flush=True,
            )
        rows.append(row)

    if args.dry_run:
        for row in rows:
            print(
                f"{row['id']:<22} "
                + "  ".join(
                    f"{c}: {r['prompt_words']} words" for c, r in row["results"].items()
                )
            )
        return 0

    means: dict[str, float] = {
        c: round(sum(r["results"][c]["score"] for r in rows) / max(len(rows), 1), 3)
        for c in conditions
    }
    print("\n" + "  ".join(f"{c}: {v:.2f}" for c, v in means.items()))
    out_dir: Path = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out: Path = out_dir / f"{common.stamp().replace(':', '')}.json"
    out.write_text(
        json.dumps(
            {
                "model": args.model,
                "conditions": conditions,
                "means": means,
                "context_words": common.word_count(context),
                "legacy_context_words": common.word_count(legacy),
                "legacy_ref": args.legacy_ref if legacy else None,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {out.relative_to(HERE.parent)}")
    for baseline in ("none", "legacy"):
        if (
            "memory" in means
            and baseline in means
            and means["memory"] <= means[baseline]
        ):
            print(
                f"FAIL: memory did not improve on the {baseline} baseline",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
