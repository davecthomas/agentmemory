"""Light tests for memory-bootstrap.py."""

from __future__ import annotations

from pathlib import Path

from conftest import run_git, run_script


def test_miner_ranks_docs_and_reasoned_commits(repo: Path) -> None:
    assert "opted in" in run_script("memory-bootstrap.py", cwd=repo).stderr
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0

    (repo / "docs").mkdir()
    (repo / "docs" / "design.md").write_text(
        "# Design\n\n## Storage decision\n\nWe keep state in git because a service "
        "would need hosting, auth, and backups that the team does not want to run "
        "for a small repo.\n\n## Install\n\nRun the script.\n",
        encoding="utf-8",
    )
    (repo / "src.py").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "add src\n\nDecision: keep src synchronous\n\nAsync gained nothing here rather than simplicity.",
    )
    (repo / "other.py").write_text("y\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "plain change with no reason")
    (repo / "newest.py").write_text("z\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "newest\n\nChosen instead of the old path because it is smaller.",
    )

    out = run_script("memory-bootstrap.py", "--limit", "4", cwd=repo)
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert "## 1. Storage decision" in text
    assert "docs/design.md § Storage decision" in text
    assert "keep src synchronous" in text
    assert "newest" in text  # first git-log record must not be dropped
    assert text.count("Kind: commit") == 2 and text.count("Kind: doc") == 1
    assert "plain change" not in text
    assert "§ Install" not in text
