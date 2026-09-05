"""Tests for bootstrap-repo, catchup, session-start, and post-compact."""

from __future__ import annotations

import json
from pathlib import Path

import common
from conftest import load, run_git, run_script


def test_bootstrap_requires_opt_in(repo: Path) -> None:
    refused = run_script("bootstrap-repo.py", cwd=repo)
    assert refused.returncode == 1
    assert "--init" in refused.stderr
    assert not (repo / common.GITHOOKS_DIR).exists()
    assert not (repo / common.CONFIG_FILE).exists()


def test_bootstrap_is_idempotent(repo: Path) -> None:
    first = run_script("bootstrap-repo.py", "--init", cwd=repo)
    assert first.returncode == 0, first.stderr
    assert common.load_json(repo / common.CONFIG_FILE, None) == common.DEFAULT_CONFIG
    for rel in (common.ADR_DIR, common.NOTES_DIR, common.LOCAL_DIR):
        assert (repo / rel).is_dir()
    assert (repo / common.ADR_DIR / "INDEX.md").is_file()
    bootstrap = load("bootstrap-repo.py")
    for name in bootstrap.HOOK_NAMES:
        hook = repo / common.GITHOOKS_DIR / name
        assert hook.read_text(encoding="utf-8") == bootstrap.hook_text(name)
        assert hook.stat().st_mode & 0o111
    assert run_git(repo, "config", "--get", "core.hooksPath") == common.GITHOOKS_DIR
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.count(bootstrap.GITIGNORE_BEGIN) == 1
    assert f"{common.LOCAL_DIR}/" in gitignore

    second = run_script("bootstrap-repo.py", cwd=repo)
    assert second.returncode == 0
    assert "writing" not in second.stderr and "creating" not in second.stderr
    assert (repo / ".gitignore").read_text(encoding="utf-8") == gitignore


def test_gitignore_block_strip_restores_original(repo: Path) -> None:
    bootstrap = load("bootstrap-repo.py")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    assert bootstrap.ensure_gitignore(repo, dry_run=False)
    assert bootstrap.strip_gitignore(repo, dry_run=False)
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n"


def test_generated_hooks_call_installed_scripts() -> None:
    bootstrap = load("bootstrap-repo.py")
    assert "project-pre-commit.sh" in bootstrap.hook_text("pre-commit")
    assert "check-memory.py" in bootstrap.hook_text("pre-commit")
    assert "commit-capture.py" in bootstrap.hook_text("post-commit")
    assert "catchup.py" in bootstrap.hook_text("post-merge")
    assert "--trigger post-merge" in bootstrap.hook_text("post-merge")


def test_catchup_reports_memory_changes_since_last_seen(repo: Path) -> None:
    first = run_script("catchup.py", "--trigger", "test", cwd=repo)
    assert first.returncode == 0, first.stderr
    assert not (repo / common.LOCAL_DIR / "catchup.md").exists()

    adr = repo / common.ADR_DIR / "ADR-0001-x.md"
    adr.parent.mkdir(parents=True)
    adr.write_text('---\nid: "ADR-0001"\ntitle: "x"\n---\n\n# x\n', encoding="utf-8")
    run_git(repo, "add", common.ADR_DIR)
    run_git(repo, "commit", "-q", "-m", "add ADR-0001")
    (repo / "unrelated.txt").write_text("x", encoding="utf-8")
    run_git(repo, "add", "unrelated.txt")
    run_git(repo, "commit", "-q", "-m", "unrelated")

    second = run_script("catchup.py", "--trigger", "post-merge", cwd=repo)
    assert second.returncode == 0, second.stderr
    digest = (repo / common.LOCAL_DIR / "catchup.md").read_text(encoding="utf-8")
    assert "# Catch-up (post-merge" in digest
    assert "add ADR-0001" in digest and "unrelated" not in digest
    assert f"A\t{common.ADR_DIR}/ADR-0001-x.md" in digest

    third = run_script("catchup.py", cwd=repo)
    assert third.returncode == 0
    assert not (repo / common.LOCAL_DIR / "catchup.md").exists()


def _settings(home: Path, configured: bool) -> None:
    common.dump_json(
        home / ".claude" / "settings.json", {common.CONFIGURED_FLAG: configured}
    )


def _opt_in(repo: Path) -> None:
    common.dump_json(repo / common.CONFIG_FILE, common.DEFAULT_CONFIG)


def test_session_start_silent_when_not_configured(repo: Path, home: Path) -> None:
    _settings(home, False)
    _opt_in(repo)
    result = run_script(
        "session-start.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    assert result.returncode == 0 and result.stdout == ""


def test_session_start_silent_when_repo_not_opted_in(repo: Path, home: Path) -> None:
    _settings(home, True)
    result = run_script(
        "session-start.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    assert result.returncode == 0 and result.stdout == ""
    assert not (repo / common.GITHOOKS_DIR).exists()
    assert not (repo / common.ADR_DIR).exists()


def test_session_start_bootstraps_and_injects(repo: Path, home: Path) -> None:
    _settings(home, True)
    _opt_in(repo)
    result = run_script(
        "session-start.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Repo wiring bootstrapped" in payload["systemMessage"]
    assert "/memory-bootstrap" in payload["hookSpecificOutput"]["additionalContext"]
    assert (repo / common.GITHOOKS_DIR / "post-commit").is_file()

    run_script(
        "promote-adr.py",
        "--title",
        "T",
        "--context",
        "c",
        "--decision",
        "the decision text",
        cwd=repo,
    )
    again = run_script(
        "session-start.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    payload = json.loads(again.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "the decision text" in context
    assert "memory-note" in context and "/memory-bootstrap" not in context
    assert payload["systemMessage"].startswith(f"agentmemory v{common.VERSION}: 1 ADRs")
    assert "bootstrapped" not in payload["systemMessage"]


def test_session_start_disabled_env_and_print_context(repo: Path, home: Path) -> None:
    _settings(home, True)
    _opt_in(repo)
    off = run_script("session-start.py", cwd=repo, env={"AGENTMEMORY_DISABLED": "1"})
    assert off.returncode == 0 and off.stdout == ""
    run_script(
        "promote-adr.py",
        "--title",
        "T",
        "--context",
        "c",
        "--decision",
        "printed decision",
        cwd=repo,
    )
    printed = run_script("session-start.py", "--print-context", cwd=repo)
    assert printed.returncode == 0 and "printed decision" in printed.stdout
    assert not printed.stdout.startswith("{")


def test_post_compact_reinjects(repo: Path, home: Path) -> None:
    run_script(
        "promote-adr.py",
        "--title",
        "T",
        "--context",
        "c",
        "--decision",
        "compact me",
        cwd=repo,
    )
    not_opted_in = run_script(
        "post-compact.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    assert not_opted_in.returncode == 0 and not_opted_in.stdout == ""
    _opt_in(repo)
    result = run_script(
        "post-compact.py", cwd=repo, stdin=json.dumps({"cwd": str(repo)})
    )
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostCompact"
    assert "compact me" in payload["hookSpecificOutput"]["additionalContext"]
