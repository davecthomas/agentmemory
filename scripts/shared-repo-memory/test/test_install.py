"""Tests for install.py and uninstall.py against a fake HOME."""

from __future__ import annotations

import subprocess
from pathlib import Path

import common
from conftest import SCRIPTS, load, run_git, run_script

CHECKOUT: Path = SCRIPTS.parents[1]


def test_install_then_uninstall_roundtrip(home: Path) -> None:
    settings = home / ".claude" / "settings.json"
    common.dump_json(
        settings,
        {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/true"}]}]
            },
            "theme": "dark",
        },
    )

    result = run_script("install.py", "--repo-root", str(CHECKOUT), cwd=CHECKOUT)
    assert result.returncode == 0, result.stderr
    root = home / ".agent" / "shared-repo-memory"
    install = load("install.py")
    for name in install.SCRIPTS:
        assert (root / name).is_file()
        assert (root / name).stat().st_mode & 0o111
    for skill in (p.name for p in (CHECKOUT / "skills").iterdir() if p.is_dir()):
        link = home / ".claude" / "skills" / skill
        assert (
            link.is_symlink()
            and link.resolve() == (home / ".agent" / "skills" / skill).resolve()
        )
        assert (link / "SKILL.md").is_file()

    data = common.load_json(settings, {})
    assert data[common.CONFIGURED_FLAG] is True
    assert data[common.ASSETS_REPO_KEY] == str(CHECKOUT)
    assert data["theme"] == "dark"
    events = {
        event: [h["command"] for e in entries for h in e["hooks"]]
        for event, entries in data["hooks"].items()
    }
    assert events["SessionStart"] == [str(root / "session-start.py")]
    assert events["PostCompact"] == [str(root / "post-compact.py")]
    assert events["Stop"] == ["/usr/bin/true"]

    again = run_script("install.py", "--repo-root", str(CHECKOUT), cwd=CHECKOUT)
    assert again.returncode == 0
    data = common.load_json(settings, {})
    assert len(data["hooks"]["SessionStart"]) == 1

    gone = run_script("uninstall.py", cwd=CHECKOUT)
    assert gone.returncode == 0, gone.stderr
    assert not root.exists()
    assert not (home / ".claude" / "skills" / "memory-bootstrap").exists()
    assert not (home / ".agent" / "skills" / "memory-bootstrap").exists()
    data = common.load_json(settings, {})
    assert common.CONFIGURED_FLAG not in data and common.ASSETS_REPO_KEY not in data
    assert data["hooks"] == {
        "Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/true"}]}]
    }
    assert data["theme"] == "dark"


def test_install_dry_run_writes_nothing(home: Path) -> None:
    result = run_script(
        "install.py", "--dry-run", "--repo-root", str(CHECKOUT), cwd=CHECKOUT
    )
    assert result.returncode == 0, result.stderr
    assert not (home / ".agent").exists()
    assert not (home / ".claude" / "settings.json").exists()
    assert "would" in result.stderr


def test_uninstall_repo_scope_reverses_bootstrap(repo: Path, home: Path) -> None:
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    (repo / common.ADR_DIR / "keep.md").write_text("x", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "wired")

    result = run_script("uninstall.py", "--repo", cwd=repo)
    assert result.returncode == 0, result.stderr
    assert not (repo / common.GITHOOKS_DIR).exists()
    hooks_path = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert hooks_path.stdout.strip() == ""
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.log\n"
    assert not (repo / common.LOCAL_DIR).exists()
    assert (repo / common.ADR_DIR / "keep.md").is_file()
    assert common.ADR_DIR in run_git(repo, "ls-files")

    purge = run_script("uninstall.py", "--repo", "--purge-memory", cwd=repo)
    assert purge.returncode == 0, purge.stderr
    assert (repo / common.ADR_DIR / "keep.md").is_file()
    assert common.ADR_DIR not in run_git(repo, "ls-files")


def test_uninstall_repo_keeps_edited_hook(repo: Path, home: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    hook = repo / common.GITHOOKS_DIR / "pre-commit"
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    assert run_script("uninstall.py", "--repo", cwd=repo).returncode == 0
    assert hook.is_file()
    assert not (repo / common.GITHOOKS_DIR / "post-commit").exists()
    assert run_git(repo, "config", "--get", "core.hooksPath") == common.GITHOOKS_DIR
