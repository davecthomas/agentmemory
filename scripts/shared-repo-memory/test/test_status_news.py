"""Light tests for memory-status.py and memory-news.py."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import run_git, run_script


def test_status_and_news_before_and_after_opt_in(repo: Path) -> None:
    assert "not opted in" in run_script("memory-status.py", cwd=repo).stdout
    assert "not opted in" in run_script("memory-news.py", cwd=repo).stdout

    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_script(
        "promote-adr.py",
        "--title",
        "Keep it simple",
        "--context",
        "c",
        "--decision",
        "one moving part",
        "--alternatives",
        "two",
        cwd=repo,
    )
    run_script("memory-note.py", "--decision", "Noted thing", "--why", "w", cwd=repo)
    (repo / "src.py").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "add src")

    status = run_script("memory-status.py", cwd=repo)
    assert status.returncode == 0, status.stderr
    assert "Opted in: yes" in status.stdout
    assert "ADRs: 1 (1 must-read, 0 superseded)" in status.stdout
    assert "Note files: 1" in status.stdout
    assert "Must-read: ADR-0001" in status.stdout
    assert "Wiring: complete" in status.stdout

    news = run_script("memory-news.py", cwd=repo)
    assert news.returncode == 0, news.stderr
    assert "Noted thing" in news.stdout
    assert "ADR-0001" in news.stdout and "Keep it simple" in news.stdout
    assert "add src" in news.stdout

    with_context = run_script("memory-status.py", "--context", cwd=repo)
    assert "## Injected context" in with_context.stdout
    assert "one moving part" in with_context.stdout


def test_news_groups_by_branch_and_cleans_names(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    note = common.load_module(Path(__file__).resolve().parents[1] / "memory-note.py")
    for i in range(2):
        (repo / f"f{i}.py").write_text("x\n", encoding="utf-8")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", f"feat/big: step {i}")
    (repo / "g.py").write_text("y\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "fix/small: one thing (#7)")
    note.append_note(
        repo,
        note.render_entry(
            decision="feat/big: chose X", why="w", author="123-alice", branch="feat/big"
        ),
    )
    out = run_script("memory-news.py", cwd=repo).stdout
    assert "### feat/big — largest" in out
    assert "### fix/small (#7)" in out
    assert "decision (alice): chose X" in out
    assert "123-alice" not in out and "feat/big: chose X" not in out
    assert out.index("### feat/big") < out.index("### fix/small")
    assert "4 commits, 1 decision note" in out  # fixture initial commit + 3


def test_news_watermark_reports_nothing_new_then_new(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    first = run_script("memory-news.py", cwd=repo).stdout
    assert "initial" in first and "Nothing new" not in first
    second = run_script("memory-news.py", cwd=repo).stdout
    assert "Nothing new since you last read news" in second
    assert "initial" in run_script("memory-news.py", "--all", cwd=repo).stdout
    (repo / "later.py").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "later change")
    third = run_script("memory-news.py", "--no-mark", cwd=repo).stdout
    assert "later change" in third and "initial" not in third
    assert "New since you last read news" in third
    assert (
        "later change" in run_script("memory-news.py", cwd=repo).stdout
    )  # --no-mark kept it
