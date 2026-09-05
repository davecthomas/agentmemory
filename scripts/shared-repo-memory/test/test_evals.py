"""Tests for evals/check_memory.py and the eval scorer."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import SCRIPTS, run_script

EVALS: Path = SCRIPTS.parents[1] / "evals"


def _check(root: Path) -> list[str]:
    return common.load_module(EVALS / "check_memory.py").run(root)


def test_check_memory_skips_repos_not_opted_in(repo: Path) -> None:
    assert _check(repo) == []


def test_check_memory_passes_on_bootstrapped_repo_with_adr_and_note(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py", "--title", "T", "--context", "c", "--decision", "d", cwd=repo
    )
    run_script("memory-note.py", "--decision", "D", "--why", "W", cwd=repo)
    assert _check(repo) == []


def test_check_memory_reports_each_problem(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py", "--title", "T", "--context", "c", "--decision", "d", cwd=repo
    )
    adr_dir = repo / common.ADR_DIR
    stray = adr_dir / "ADR-0002-stray.md"
    stray.write_text("# no frontmatter\n\nSee [gone](missing.md).\n", encoding="utf-8")
    (repo / common.NOTES_DIR / "badname.md").write_text("## x\n", encoding="utf-8")
    (repo / common.NOTES_DIR / "2026-01-01.md").write_text(
        "# n\n\n## h\n\n**Why:** only\n", encoding="utf-8"
    )
    problems = "\n".join(_check(repo))
    assert "ADR-0002-stray.md: missing from INDEX.md" in problems
    assert "frontmatter lacks id" in problems
    assert "link to missing missing.md" in problems
    assert "badname.md: note files must be named" in problems
    assert "2026-01-01.md entry 1: missing **Decision:** line" in problems


def test_check_memory_flags_must_read_over_budget(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    common.dump_json(
        repo / common.CONFIG_FILE, {**common.DEFAULT_CONFIG, "context_budget_words": 20}
    )
    for i in range(3):
        run_script(
            "promote-adr.py",
            "--title",
            f"T{i}",
            "--context",
            "c",
            "--decision",
            "word " * 15,
            cwd=repo,
        )
    problems = "\n".join(_check(repo))
    assert "must-read ADRs do not fit the budget" in problems


def test_eval_scorer_accepts_alternatives() -> None:
    run_eval = common.load_module(EVALS / "run_eval.py")
    value, missed = run_eval.score(
        "We keep memory in Git as Markdown.",
        ["git", ["markdown", "plain text"], "vector"],
    )
    assert value == round(2 / 3, 3) or abs(value - 2 / 3) < 1e-9
    assert missed == ["vector"]
    assert run_eval.score("anything", []) == (1.0, [])
