"""Tests for memory-commit.py."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import run_git, run_script


def _mc(*args: str, cwd: Path):
    return run_script("memory-commit.py", *args, cwd=cwd)


def test_requires_opt_in_and_reports_nothing_to_do(repo: Path) -> None:
    assert _mc(cwd=repo).returncode == 1
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "opt in")
    result = _mc(cwd=repo)
    assert result.returncode == 0 and "no uncommitted decision memory" in result.stderr


def test_first_commit_message_lists_decisions_and_adrs(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "opt in")
    run_script("memory-note.py", "--decision", "Use a queue", "--why", "w", cwd=repo)
    run_script(
        "promote-adr.py",
        "--title",
        "Queues for retries",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    result = _mc("--no-stage", cwd=repo)
    assert result.returncode == 0, result.stderr
    msg = result.stdout
    assert msg.startswith("memory: 1 decision and 1 ADR from ")
    assert "- ADR-0001 (accepted): Queues for retries" in msg
    assert "Use a queue" in msg
    assert "first decision-memory commit" in msg  # pointer, once
    assert f"{common.NOTES_DIR}/" in result.stderr


def test_commit_creates_one_memory_only_commit_then_is_idempotent(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "opt in")
    run_script("memory-note.py", "--decision", "First call", "--why", "w", cwd=repo)
    (repo / "code.py").write_text("x\n", encoding="utf-8")

    assert _mc("--commit", cwd=repo).returncode == 0
    files = run_git(repo, "show", "--format=", "--name-only", "HEAD").split()
    assert files and all(f.startswith(common.MEMORY_DIR) for f in files)
    assert "code.py" in run_git(repo, "status", "--porcelain")  # code untouched

    again = _mc(cwd=repo)
    assert again.returncode == 0 and "no uncommitted" in again.stderr

    run_script("memory-note.py", "--decision", "Second call", "--why", "w", cwd=repo)
    msg = _mc("--no-stage", cwd=repo).stdout
    assert "Second call" in msg and "First call" not in msg  # only what is new
    assert "first decision-memory commit" not in msg  # short pointer now
    assert "Captured by agentmemory" in msg


def test_local_cache_is_never_included(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    common.write_text(repo / common.LOCAL_DIR / "catchup.md", "local only\n")
    run_script("memory-note.py", "--decision", "D", "--why", "W", cwd=repo)
    listed = _mc("--no-stage", cwd=repo).stderr
    assert common.NOTES_DIR in listed and common.LOCAL_DIR not in listed


def test_opt_in_files_ride_with_the_first_memory_commit(repo: Path) -> None:
    (repo / "AGENTS.md").write_text("# Rules\n\nBe kind.\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "add rules")
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0

    msg = _mc("--no-stage", cwd=repo).stdout
    assert msg.startswith("memory: turn on decision memory from ")
    assert "Opting this repository in" in msg
    assert ".gitignore" in msg and "AGENTS.md" in msg

    assert _mc("--commit", cwd=repo).returncode == 0
    files = run_git(repo, "show", "--format=", "--name-only", "HEAD").split()
    assert ".gitignore" in files and "AGENTS.md" in files
    assert f"{common.ADR_DIR}/INDEX.md" in files
    assert not run_git(repo, "status", "--porcelain", "--", ".gitignore", "AGENTS.md")


def test_opt_in_file_with_unrelated_edits_is_left_alone(repo: Path) -> None:
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "gitignore")
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    # The developer edits the same file for their own reasons.
    gi = repo / ".gitignore"
    gi.write_text(
        gi.read_text(encoding="utf-8") + "\nnode_modules/\n", encoding="utf-8"
    )

    result = _mc("--no-stage", cwd=repo)
    assert (
        ".gitignore carries the agentmemory block alongside your own edits"
        in result.stderr
    )
    assert ".gitignore" not in result.stdout
    assert _mc("--commit", cwd=repo).returncode == 0
    assert ".gitignore" not in run_git(repo, "show", "--format=", "--name-only", "HEAD")
    assert "node_modules" in (repo / ".gitignore").read_text(encoding="utf-8")
