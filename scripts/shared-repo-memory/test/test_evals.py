"""Tests for evals/check_memory.py and the eval scorer."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import SCRIPTS, run_script

EVALS: Path = SCRIPTS.parents[1] / "evals"


def _check(root: Path) -> list[str]:
    return common.load_module(SCRIPTS / "check-memory.py").run(root)


def test_check_memory_skips_repos_not_opted_in(repo: Path) -> None:
    assert _check(repo) == []


def test_check_memory_passes_on_bootstrapped_repo_with_adr_and_note(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py",
        "--title",
        "T",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "None viable; recorded for the check.",
        cwd=repo,
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


def test_check_memory_flags_placeholder_alternatives(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py", "--title", "T", "--context", "c", "--decision", "d", cwd=repo
    )
    assert any("placeholder Alternatives" in p for p in _check(repo))
    run_script(
        "promote-adr.py",
        "--title",
        "U",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "Considered X; rejected because Y.",
        cwd=repo,
    )
    problems = _check(repo)
    assert sum("placeholder Alternatives" in p for p in problems) == 1


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
            "--alternatives",
            "a",
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


def test_eval_dry_run_builds_news_prompt() -> None:
    import subprocess
    import sys

    repo_root = SCRIPTS.parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(EVALS / "run_eval.py"),
            "--dry-run",
            "--only",
            "news-narrative",
            "--conditions",
            "none,memory",
            "--repo-root",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    line = next(
        ln for ln in result.stdout.splitlines() if ln.startswith("news-narrative")
    )
    words = int(line.split("memory:")[1].split()[0])
    assert words > 200  # the digest, not just the question


def test_judge_never_grades_error_answers() -> None:
    run_eval = common.load_module(EVALS / "run_eval.py")
    graded = run_eval.judge(
        "q", "ref", "[claude exited 1: ]", model=None, cwd=Path("/tmp"), timeout=1
    )
    assert graded is None


def test_check_memory_detects_duplicate_ids_and_dangling_supersedes(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py",
        "--title",
        "First",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    # What a merge of two concurrent branches leaves behind: a second file
    # claiming the same id, listed under that id in the index.
    adr_dir = repo / common.ADR_DIR
    clash = adr_dir / "ADR-0001-second.md"
    clash.write_text(
        (adr_dir / "ADR-0001-first.md")
        .read_text(encoding="utf-8")
        .replace("First", "Second"),
        encoding="utf-8",
    )
    index = adr_dir / "INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8")
        + "| ADR-0001 | [Second](ADR-0001-second.md) | accepted | 2026-01-01 | yes |\n",
        encoding="utf-8",
    )
    problems = "\n".join(_check(repo))
    assert "ADR-0001 is claimed by 2 files" in problems
    assert "INDEX.md: ADR-0001 appears in 2 rows" in problems


def test_check_memory_flags_supersedes_that_names_no_adr(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py",
        "--title",
        "Only",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        "--supersedes",
        "ADR-0009",
        cwd=repo,
    )
    assert any(
        "supersedes names ADR-0009, which matches 0 ADRs" in p for p in _check(repo)
    )
